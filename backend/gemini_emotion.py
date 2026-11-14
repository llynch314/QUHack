"""Facial expression reading with Gemini (gemini-3.8-flash by default).

Returns one of DeepFace's old 7 labels so the rest of the app is unchanged.
"""
import json

import cv2
from google.genai import types

from gemini_client import CHAT_MODEL, get_client

EMOTIONS = ['angry', 'disgust', 'fear', 'happy', 'sad', 'surprise', 'neutral']

PROMPT = (
    "Classify the facial expression of the main person in this image. If there is no "
    "clearly visible face, answer none."
)

_CONFIG = types.GenerateContentConfig(
    temperature=0,
    response_mime_type='application/json',
    response_schema={
        'type': 'OBJECT',
        'properties': {'emotion': {'type': 'STRING', 'enum': EMOTIONS + ['none']}},
        'required': ['emotion'],
    },
    thinking_config=types.ThinkingConfig(thinking_level='low'),
)


class NoFaceDetected(ValueError):
    """Raised when Gemini sees no face in the image."""


def detect_emotion(img_bytes, mime_type='image/png'):
    """Return the dominant emotion (one of EMOTIONS) for an encoded image.

    Raises NoFaceDetected if there is no face, ValueError on an unexpected answer.
    """
    response = get_client().models.generate_content(
        model=CHAT_MODEL,
        contents=[PROMPT, types.Part.from_bytes(data=img_bytes, mime_type=mime_type)],
        config=_CONFIG,
    )
    try:
        emotion = str(json.loads(response.text)['emotion']).strip().lower()
    except (TypeError, ValueError, KeyError):
        emotion = ''
    if emotion == 'none':
        raise NoFaceDetected("No face detected")
    if emotion not in EMOTIONS:
        raise ValueError(f"Unexpected Gemini response: {response.text!r}")
    return emotion


def detect_emotion_frame(frame):
    """Same as detect_emotion, for an OpenCV (BGR) frame."""
    ok, buf = cv2.imencode('.jpg', frame)
    if not ok:
        raise ValueError("Could not encode frame as JPEG")
    return detect_emotion(buf.tobytes(), 'image/jpeg')
