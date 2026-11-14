"""Facial expression reading with Claude (claude-opus-5-5 by default).

Returns one of DeepFace's old 7 labels so the rest of the app is unchanged.
"""
import base64
import json

import cv2

from claude_client import CHAT_MODEL, FALLBACK_BETA, get_client, reply_text

EMOTIONS = ['angry', 'disgust', 'fear', 'happy', 'sad', 'surprise', 'neutral']

PROMPT = (
    "Classify the facial expression of the main person in this image. If there is no "
    "clearly visible face, answer none."
)

_FORMAT = {
    'type': 'json_schema',
    'schema': {
        'type': 'object',
        'properties': {'emotion': {'type': 'string', 'enum': EMOTIONS + ['none']}},
        'required': ['emotion'],
        'additionalProperties': False,
    },
}


class NoFaceDetected(ValueError):
    """Raised when Claude sees no face in the image."""


def detect_emotion(img_bytes, mime_type='image/png'):
    """Return the dominant emotion (one of EMOTIONS) for an encoded image.

    Raises NoFaceDetected if there is no face, ValueError on an unexpected answer.
    """
    response = get_client().beta.messages.create(
        model=CHAT_MODEL,
        max_tokens=1024,
        messages=[{'role': 'user', 'content': [
            {'type': 'image', 'source': {
                'type': 'base64', 'media_type': mime_type,
                'data': base64.standard_b64encode(img_bytes).decode('ascii')}},
            {'type': 'text', 'text': PROMPT},
        ]}],
        output_config={'effort': 'low', 'format': _FORMAT},
        betas=[FALLBACK_BETA],
        fallbacks='default',
    )
    text = reply_text(response)
    try:
        emotion = str(json.loads(text)['emotion']).strip().lower()
    except (TypeError, ValueError, KeyError):
        emotion = ''
    if emotion == 'none':
        raise NoFaceDetected("No face detected")
    if emotion not in EMOTIONS:
        raise ValueError(f"Unexpected Claude response: {text!r}")
    return emotion


def detect_emotion_frame(frame):
    """Same as detect_emotion, for an OpenCV (BGR) frame."""
    ok, buf = cv2.imencode('.jpg', frame)
    if not ok:
        raise ValueError("Could not encode frame as JPEG")
    return detect_emotion(buf.tobytes(), 'image/jpeg')
