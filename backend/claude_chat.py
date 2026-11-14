"""Text chat with Claude (claude-opus-5-5 by default)."""
from claude_client import CHAT_EFFORT, CHAT_MODEL, FALLBACK_BETA, get_client, reply_text
from prompts import CRISIS_FALLBACK, SYSTEM_PROMPT, mentions_crisis

MAX_TURNS = 20          # how much recent conversation is sent to Claude
MAX_CHARS = 4000        # per message


def _messages(history):
    """Convert [{'role': 'user'|'model', 'text': ...}] into Claude messages."""
    messages = []
    for msg in history[-MAX_TURNS:]:
        role = 'assistant' if msg.get('role') == 'model' else 'user'
        text = str(msg.get('text', ''))[:MAX_CHARS].strip()
        if text:
            messages.append({'role': role, 'content': text})
    # Claude conversations must start with a user turn.
    while messages and messages[0]['role'] == 'assistant':
        messages.pop(0)
    return messages


def chat_reply(history, emotion=None):
    """Return {'reply': str, 'crisis': bool} for a conversation history.

    `emotion` is the optional webcam reading; it is passed as a soft hint only.
    """
    last_user = next((m.get('text', '') for m in reversed(history) if m.get('role') != 'model'), '')
    crisis = mentions_crisis(last_user)

    # The stable system prompt is cached; the per-request emotion hint comes after it.
    system = [{'type': 'text', 'text': SYSTEM_PROMPT, 'cache_control': {'type': 'ephemeral'}}]
    if emotion:
        system.append({'type': 'text', 'text': (
            f"The user opted in to webcam expression reading; their face currently "
            f"looks '{emotion}'. Treat this as an uncertain hint, never as fact, and "
            f"don't mention it unless it helps (e.g. 'you look a bit tense - is that right?').")})

    messages = _messages(history)
    reply = ''
    if messages:
        response = get_client().beta.messages.create(
            model=CHAT_MODEL,
            max_tokens=16000,
            system=system,
            messages=messages,
            output_config={'effort': CHAT_EFFORT},
            betas=[FALLBACK_BETA],
            fallbacks='default',
        )
        reply = reply_text(response)
    if not reply:
        # Never leave the user with nothing.
        reply = CRISIS_FALLBACK if crisis else "Sorry, I couldn't come up with a reply just now. Could you say that another way?"
    return {'reply': reply, 'crisis': crisis}


def generate_response(user_input):
    """Single-message helper kept for older code."""
    return chat_reply([{'role': 'user', 'text': user_input}])['reply']
