"""Voice mode: relays audio between the browser and the Gemini Live API.

The API key stays on the server. Browser <-> /ws/voice protocol:
  browser -> server  binary: 16 kHz mono 16-bit PCM microphone audio
                     text:   {"type": "text", "text": "..."}  (typed message)
                             {"type": "stop"}
  server -> browser  binary: 24 kHz mono 16-bit PCM audio from Gemini
                     text:   {"type": "ready" | "turn_complete" | "interrupted" | "crisis"}
                             {"type": "transcript", "who": "user" | "model", "text": "..."}
                             {"type": "error", "message": "..."}
"""
import asyncio
import json
import logging

from flask import request
from flask_sock import Sock
from google.genai import types
from simple_websocket import ConnectionClosed

from gemini_client import (
    LIVE_MODEL, LIVE_THINKING_MODEL, SYSTEM_PROMPT, VOICE_PROMPT_SUFFIX, get_client, mentions_crisis,
)

log = logging.getLogger(__name__)
sock = Sock()

THINKING_LEVELS = {'low', 'medium', 'high'}  # MINIMAL is not supported on extended thinking


def live_config(extended, level):
    config = {
        'response_modalities': ['AUDIO'],          # Live models only reply with audio
        'system_instruction': SYSTEM_PROMPT + VOICE_PROMPT_SUFFIX,
        'input_audio_transcription': {},           # text of what the user said
        'output_audio_transcription': {},          # text of what Gemini said
    }
    # thinking_level must be omitted for gemini-3.8-live (reasoning is built in).
    if extended:
        config['thinking_config'] = {'thinking_level': level if level in THINKING_LEVELS else 'medium'}
    return config


def _send_json(ws, **payload):
    ws.send(json.dumps(payload))


@sock.route('/ws/voice')
def voice_socket(ws):
    extended = request.args.get('mode') == 'extended'
    level = request.args.get('thinking', 'medium')
    model = LIVE_THINKING_MODEL if extended else LIVE_MODEL
    try:
        asyncio.run(_relay(ws, model, live_config(extended, level)))
    except ConnectionClosed:
        pass
    except Exception as e:  # report to the browser instead of failing silently
        log.exception('Voice session failed')
        try:
            _send_json(ws, type='error', message=str(e))
        except ConnectionClosed:
            pass


async def _relay(ws, model, config):
    async with get_client().aio.live.connect(model=model, config=config) as session:
        _send_json(ws, type='ready', model=model)

        async def browser_to_gemini():
            while True:
                try:
                    msg = await asyncio.to_thread(ws.receive)
                except ConnectionClosed:
                    return
                if msg is None:
                    return
                if isinstance(msg, (bytes, bytearray)):
                    await session.send_realtime_input(
                        audio=types.Blob(data=bytes(msg), mime_type='audio/pcm;rate=16000'))
                    continue
                data = json.loads(msg)
                if data.get('type') == 'stop':
                    return
                if data.get('type') == 'text' and data.get('text'):
                    text = str(data['text'])[:2000]
                    if mentions_crisis(text):
                        _send_json(ws, type='crisis')
                    await session.send_realtime_input(text=text)

        async def gemini_to_browser():
            while True:  # receive() ends after each model turn, so keep listening
                async for message in session.receive():
                    if message.data:
                        ws.send(message.data)
                    content = message.server_content
                    if not content:
                        continue
                    if content.input_transcription and content.input_transcription.text:
                        heard = content.input_transcription.text
                        _send_json(ws, type='transcript', who='user', text=heard)
                        if mentions_crisis(heard):
                            _send_json(ws, type='crisis')
                    if content.output_transcription and content.output_transcription.text:
                        _send_json(ws, type='transcript', who='model', text=content.output_transcription.text)
                    if content.interrupted:
                        _send_json(ws, type='interrupted')
                    if content.turn_complete:
                        _send_json(ws, type='turn_complete')

        tasks = [asyncio.create_task(browser_to_gemini()), asyncio.create_task(gemini_to_browser())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            if task.exception() and not isinstance(task.exception(), ConnectionClosed):
                raise task.exception()
    # Closing the socket also unblocks the thread waiting in ws.receive().
    ws.close()
