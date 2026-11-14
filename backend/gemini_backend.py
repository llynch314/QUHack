"""Text chat with Gemini (gemini-3.8-flash by default)."""
from google.genai import types

from gemini_client import (
    CHAT_MODEL, CHAT_THINKING_LEVEL, CRISIS_FALLBACK, SYSTEM_PROMPT, get_client, mentions_crisis,
)

MAX_TURNS = 20          # how much recent conversation is sent to Gemini
MAX_CHARS = 4000        # per message


def _contents(history):
    """Convert [{'role': 'user'|'model', 'text': ...}] into Gemini contents."""
    contents = []
    for msg in history[-MAX_TURNS:]:
        role = 'model' if msg.get('role') == 'model' else 'user'
        text = str(msg.get('text', ''))[:MAX_CHARS].strip()
        if text:
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))
    return contents


def chat_reply(history, emotion=None):
    """Return {'reply': str, 'crisis': bool} for a conversation history.

    `emotion` is the optional webcam reading; it is passed as a soft hint only.
    """
    last_user = next((m.get('text', '') for m in reversed(history) if m.get('role') != 'model'), '')
    crisis = mentions_crisis(last_user)

    system = SYSTEM_PROMPT
    if emotion:
        system += (f"\nThe user opted in to webcam expression reading; their face currently "
                   f"looks '{emotion}'. Treat this as an uncertain hint, never as fact, and "
                   f"don't mention it unless it helps (e.g. 'you look a bit tense - is that right?').")

    response = get_client().models.generate_content(
        model=CHAT_MODEL,
        contents=_contents(history),
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.7,
            thinking_config=types.ThinkingConfig(thinking_level=CHAT_THINKING_LEVEL),
        ),
    )
    reply = (response.text or '').strip()
    if not reply:
        # Safety filters can block replies on sensitive topics; never leave the user with nothing.
        reply = CRISIS_FALLBACK if crisis else "Sorry, I couldn't come up with a reply just now. Could you say that another way?"
    return {'reply': reply, 'crisis': crisis}


def generate_response(user_input):
    """Single-message helper kept for older code."""
    return chat_reply([{'role': 'user', 'text': user_input}])['reply']
