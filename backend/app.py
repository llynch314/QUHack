"""Mind Connect web app. Run with `make run` (or `python app.py` from backend/)."""
import base64
import logging
import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request, session

load_dotenv()

from auth import bp as auth_bp, init_auth, login_required  # noqa: E402
from gemini_backend import chat_reply  # noqa: E402
from gemini_emotion import NoFaceDetected, detect_emotion  # noqa: E402
from models import CheckIn, db  # noqa: E402
from voice import sock  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, '..', 'frontend')
ACTIVITIES = {'breathing', 'grounding', 'thought-record', 'chat', 'voice', 'general'}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('mindconnect')

app = Flask(
    __name__,
    template_folder=os.path.join(FRONTEND_DIR, 'templates'),
    static_folder=os.path.join(FRONTEND_DIR, 'static'),
)

secret = os.getenv('FLASK_SECRET_KEY')
if not secret:
    secret = secrets.token_hex(32)
    log.warning('FLASK_SECRET_KEY is not set; using a random key, so sign-ins reset on every restart.')
app.config.update(
    SECRET_KEY=secret,
    SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL', 'sqlite:///mindconnect.db'),  # file in backend/instance/
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,   # webcam frames are well under this
)

db.init_app(app)
init_auth(app)
sock.init_app(app)
app.register_blueprint(auth_bp)

with app.app_context():
    db.create_all()


# ---------- Pages ----------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/chat')
def chat():
    return render_template('chat.html')


@app.route('/toolkit')
def toolkit():
    return render_template('toolkit.html')


@app.route('/report')
@login_required
def report():
    checkins = g.user.checkins
    rated = [c for c in checkins if c.stress_before is not None and c.stress_after is not None]
    avg_change = (sum(c.stress_after - c.stress_before for c in rated) / len(rated)) if rated else None
    diffs = {}
    for c in rated:
        diffs.setdefault(c.activity, []).append(c.stress_after - c.stress_before)
    # [(activity, average change, count)], biggest drop in stress first
    by_activity = sorted(((a, sum(d) / len(d), len(d)) for a, d in diffs.items()), key=lambda t: t[1])
    return render_template('report.html', checkins=checkins, avg_change=avg_change, by_activity=by_activity)


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


# ---------- JSON API ----------

def _error(message, status):
    return jsonify(error=message), status


@app.post('/api/chat')
def api_chat():
    data = request.get_json(silent=True) or {}
    history = data.get('messages')
    if not isinstance(history, list) or not history:
        return _error('No messages sent.', 400)
    emotion = data.get('emotion') if isinstance(data.get('emotion'), str) else None
    try:
        return jsonify(chat_reply(history, emotion))
    except RuntimeError as e:          # missing API key
        return _error(str(e), 503)
    except Exception:
        log.exception('Gemini chat failed')
        return _error("The AI service isn't responding right now. Please try again in a moment.", 502)


@app.post('/api/emotion')
def api_emotion():
    data = request.get_json(silent=True) or {}
    image = data.get('image_data', '')
    if ',' not in image:
        return _error('Expected an image data URL.', 400)
    header, b64 = image.split(',', 1)  # header looks like 'data:image/jpeg;base64'
    mime_type = header[5:].split(';')[0] if header.startswith('data:') else 'image/jpeg'
    if mime_type not in ('image/jpeg', 'image/png', 'image/webp'):
        return _error('Unsupported image type.', 400)
    try:
        return jsonify(emotion=detect_emotion(base64.b64decode(b64), mime_type))
    except NoFaceDetected:
        return jsonify(emotion=None)
    except RuntimeError as e:
        return _error(str(e), 503)
    except Exception:
        log.exception('Gemini emotion detection failed')
        return _error('Emotion detection failed.', 502)


def _rating(value):
    if value is None or value == '':
        return None
    value = int(value)
    if not 0 <= value <= 10:
        raise ValueError
    return value


@app.route('/api/checkins', methods=['GET', 'POST'])
@login_required
def api_checkins():
    if request.method == 'GET':
        return jsonify(checkins=[c.to_dict() for c in g.user.checkins])
    data = request.get_json(silent=True) or {}
    try:
        before, after = _rating(data.get('stress_before')), _rating(data.get('stress_after'))
    except (TypeError, ValueError):
        return _error('Ratings must be whole numbers from 0 to 10.', 400)
    activity = data.get('activity', 'general')
    if activity not in ACTIVITIES:
        return _error('Unknown activity.', 400)
    if before is None and after is None:
        return _error('Add at least one rating.', 400)
    note = (data.get('note') or '').strip()[:500] or None
    checkin = CheckIn(user_id=g.user.id, activity=activity, stress_before=before,
                      stress_after=after, note=note)
    db.session.add(checkin)
    db.session.commit()
    return jsonify(checkin=checkin.to_dict()), 201


@app.post('/api/me/delete')
@login_required
def api_delete_me():
    """Delete the account and every check-in. Required for user control over their data."""
    db.session.delete(g.user)
    db.session.commit()
    session.clear()
    return jsonify(deleted=True)


if __name__ == '__main__':
    app.run(debug=True)
