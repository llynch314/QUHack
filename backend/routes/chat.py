"""Chatbot and emotion detection. Private to the patient."""
import base64

from flask import Blueprint, abort, g, jsonify, request

import gemini_backend
from auth import roles_required
from models import ChatMessage, db
from routes.alerts import create_alert
from safety import CRISIS_RESOURCES, detect_urgent

bp = Blueprint("chat", __name__, url_prefix="/api")

HISTORY_LIMIT = 20  # messages of context sent to the model

ALERT_NOTES = {
    "crisis": "Mind Connect detected signs of a crisis. Please check in with them now.",
    "panic_attack": "Mind Connect detected signs of a panic attack. Please check in with them.",
    "meltdown": "Mind Connect detected signs of a meltdown. Please check in with them.",
}


@bp.get("/chat")
@roles_required("patient")
def history():
    msgs = (ChatMessage.query.filter_by(patient_id=g.user.id)
            .order_by(ChatMessage.id.desc()).limit(100).all())
    return jsonify(messages=[m.to_dict() for m in reversed(msgs)])


@bp.post("/chat")
@roles_required("patient")
def send():
    data = request.get_json(silent=True) or {}
    text = (data.get("message") or "").strip()
    if not text:
        abort(400, "message is required.")

    past = (ChatMessage.query.filter_by(patient_id=g.user.id)
            .order_by(ChatMessage.id.desc()).limit(HISTORY_LIMIT).all())
    history = [{"sender": m.sender, "text": m.text} for m in reversed(past)]

    reply = gemini_backend.generate_response(text, history, data.get("emotion"))

    urgent = detect_urgent(text)
    alert = None
    if urgent == "crisis" and "988" not in reply:
        reply = f"{reply}\n\n{CRISIS_RESOURCES}"
    if urgent and g.user.auto_alerts:
        # Family sees only that something happened, never the chat text itself.
        alert = create_alert(g.user.id, urgent, "chat", ALERT_NOTES[urgent])

    db.session.add_all([
        ChatMessage(patient_id=g.user.id, sender="user", text=text),
        ChatMessage(patient_id=g.user.id, sender="model", text=reply),
    ])
    db.session.commit()
    return jsonify(reply=reply, urgent=urgent,
                   alert_sent=alert is not None)


@bp.delete("/chat")
@roles_required("patient")
def clear():
    ChatMessage.query.filter_by(patient_id=g.user.id).delete()
    db.session.commit()
    return "", 204


@bp.post("/detect_emotion")
@roles_required("patient")
def detect_emotion():
    """Body: {"image_data": "data:image/png;base64,..."} -> {"emotion": "sad"}"""
    data = request.get_json(silent=True) or {}
    image_data = data.get("image_data") or ""
    try:
        raw = base64.b64decode(image_data.split(",")[-1], validate=True)
    except (ValueError, TypeError):
        abort(400, "image_data must be a base64 image.")

    # Heavy imports kept local so the rest of the API starts fast without them.
    import cv2
    import numpy as np
    from deepface import DeepFace

    frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        abort(400, "Couldn't read that image.")
    try:
        result = DeepFace.analyze(frame, actions=["emotion"], silent=True)
    except ValueError:
        return jsonify(emotion=None, error="No face detected."), 200
    return jsonify(emotion=result[0]["dominant_emotion"])
