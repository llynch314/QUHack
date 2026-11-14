"""Gemini setup for voice mode only (Gemini Live: audio in, audio out + transcripts).

Text chat and the webcam expression check use Claude (see claude_client.py). Claude
has no real-time audio API, so voice mode still relays to Gemini Live and needs
GEMINI_API_KEY in backend/.env. Model names can be changed in .env.
"""
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

LIVE_MODEL = os.getenv('GEMINI_LIVE_MODEL', 'gemini-3.1-flash-live-preview')

_client = None


def get_client():
    """Create the Gemini client on first use, so the app still starts without a key."""
    global _client
    if _client is None:
        key = os.getenv('GEMINI_API_KEY', '').strip()
        if not key or key == 'your_key_here':
            raise RuntimeError('Voice mode needs GEMINI_API_KEY in backend/.env')
        # v1beta is required for the Live API.
        _client = genai.Client(api_key=key, http_options={'api_version': 'v1beta'})
    return _client
