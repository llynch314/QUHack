"""Gemini chatbot wrapper with a mental-health system prompt and conversation memory.

Uses Google's current Python SDK, `google-genai`.
"""
import os

from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

SYSTEM_PROMPT = """You are AttuneMind, a warm, supportive mental health companion.
- Listen first. Reflect back what the person is feeling before offering suggestions.
- Keep replies short (2-5 sentences) and conversational, never clinical or preachy.
- Offer simple, evidence-based coping ideas when helpful (slow breathing, grounding
  with the 5-4-3-2-1 senses exercise, reaching out to someone they trust).
- You are not a therapist or doctor. Don't diagnose or discuss medication doses;
  encourage professional help for ongoing struggles.
- If the person mentions suicide, self-harm, or being in danger, respond with care
  and urge them to contact the 988 Suicide & Crisis Lifeline (call or text 988 in
  the US) or emergency services right away."""

_client = None


def _get_client():
    global _client
    from google import genai  # imported lazily so tests run without it

    if _client is None:
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _client


def generate_response(user_input, history=None, emotion=None):
    """Reply to `user_input`.

    history: list of {"sender": "user"|"model", "text": str}, oldest first.
    emotion: optional dominant emotion from the webcam (e.g. "sad").
    """
    from google.genai import types

    try:
        chat = _get_client().chats.create(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
            history=[
                types.Content(role=m["sender"], parts=[types.Part(text=m["text"])])
                for m in (history or [])
            ],
        )
        message = user_input
        if emotion:
            message = (f"[Context: the user's facial expression currently looks {emotion}. "
                       f"Use this gently; don't mention the camera unless relevant.]\n{user_input}")
        return chat.send_message(message).text
    except Exception as e:
        return f"Sorry, I'm having trouble responding right now. ({e})"
