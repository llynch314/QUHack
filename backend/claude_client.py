"""Shared Claude setup: one Anthropic API client and model settings.

Reads ANTHROPIC_API_KEY from backend/.env. The model and effort can be changed in
.env without touching code.
"""
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

# Text chat and webcam emotion (text + images in, text out).
CHAT_MODEL = os.getenv('CLAUDE_CHAT_MODEL', 'claude-opus-5-5')
# low / medium / high / xhigh / max. Low keeps chat replies fast; raise it for deeper replies.
CHAT_EFFORT = os.getenv('CLAUDE_EFFORT', 'low')

# If a reply is declined by Claude's safety classifiers, the API retries it on a
# fallback model inside the same call instead of leaving the user with nothing.
FALLBACK_BETA = 'server-side-fallback-2026-07-01'

_client = None


def get_client():
    """Create the Claude client on first use, so the app still starts without a key."""
    global _client
    if _client is None:
        key = os.getenv('ANTHROPIC_API_KEY', '').strip()
        if not key or key == 'your_key_here':
            raise RuntimeError('ANTHROPIC_API_KEY is not set in backend/.env')
        _client = anthropic.Anthropic(api_key=key)
    return _client


def reply_text(response):
    """Join the text blocks of a Claude response ('' if it was refused or empty)."""
    if response.stop_reason == 'refusal':
        return ''
    return ''.join(b.text for b in response.content if b.type == 'text').strip()
