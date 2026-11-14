"""AttuneMIND web app. Run with `make run` (or `python app.py` from backend/)."""
import base64
import csv
import logging
import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv
<<<<<<< HEAD
from flask import (
    Flask, g, jsonify, render_template, request, send_from_directory, session,
)
=======
from flask import Flask, g, jsonify, render_template, request, session
import anthropic
>>>>>>> df38e44cf0e8ead19d8d57129474b64c9d301cfa

load_dotenv()

from auth import bp as auth_bp, init_auth, login_required, roles_required  # noqa: E402
from care import alert_from_chat, bp as care_bp  # noqa: E402
from claude_chat import chat_reply  # noqa: E402
from claude_emotion import NoFaceDetected, detect_emotion  # noqa: E402
from models import CheckIn, ExpressionReading, add_missing_columns, as_utc, db, delete_user_everywhere  # noqa: E402
from safety import detect_urgent  # noqa: E402
from voice import sock  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, '..', 'frontend')
ACTIVITIES = {'breathing', 'grounding', 'thought-record', 'chat', 'voice', 'general'}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('attunemind')

app = Flask(
    __name__,
    template_folder=os.path.join(FRONTEND_DIR, 'templates'),
    static_folder=os.path.join(FRONTEND_DIR, 'static'),
)

secret = os.getenv('FLASK_SECRET_KEY') or os.getenv('SECRET_KEY')
if not secret:
    secret = secrets.token_hex(32)
    log.warning('FLASK_SECRET_KEY is not set; using a random key, so sign-ins reset on every restart.')
app.config.update(
    SECRET_KEY=secret,
    SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL', 'sqlite:///attunemind.db'),  # file in backend/instance/
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,   # webcam frames are well under this
)

db.init_app(app)
init_auth(app)
sock.init_app(app)
app.register_blueprint(auth_bp)
app.register_blueprint(care_bp)
app.add_template_filter(lambda dt: as_utc(dt).isoformat(), 'iso')   # for <time datetime=...>

with app.app_context():
    db.create_all()
    add_missing_columns()

# Expression readings are also appended here (and printed in the terminal) for demos.
os.makedirs(app.instance_path, exist_ok=True)
EXPRESSION_LOG = os.path.join(app.instance_path, 'expression_log.csv')


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
@roles_required('patient')
def report():
    checkins = g.user.checkins
    rated = [c for c in checkins if c.stress_before is not None and c.stress_after is not None]
    avg_change = (sum(c.stress_after - c.stress_before for c in rated) / len(rated)) if rated else None
    diffs = {}
    for c in rated:
        diffs.setdefault(c.activity, []).append(c.stress_after - c.stress_before)
    # [(activity, average change, count)], biggest drop in stress first
    by_activity = sorted(((a, sum(d) / len(d), len(d)) for a, d in diffs.items()), key=lambda t: t[1])
    readings = g.user.expressions
    expression_counts = {}
    for r in readings:
        expression_counts[r.emotion] = expression_counts.get(r.emotion, 0) + 1
    return render_template('report.html', checkins=checkins, avg_change=avg_change, by_activity=by_activity,
                           readings=readings[-50:], expression_counts=sorted(expression_counts.items(), key=lambda t: -t[1]),
                           total_readings=len(readings))


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/test')
@login_required
def test_dashboard():
    return send_from_directory(FRONTEND_DIR, 'test.html')


# ---------- JSON API ----------

def _error(message, status):
    return jsonify(error=message), status


<<<<<<< HEAD
@app.get('/api/me')
@login_required
def api_me():
    return jsonify(name=g.user.name or 'there')
=======
QUOTA_MESSAGE = 'The AI usage limit has been reached for now. Please try again later.'


def _is_quota_error(exc):
    """True when Claude rejected the call because of rate limits or quota (HTTP 429)."""
    return isinstance(exc, anthropic.RateLimitError)
>>>>>>> df38e44cf0e8ead19d8d57129474b64c9d301cfa


@app.post('/api/chat')
def api_chat():
    data = request.get_json(silent=True) or {}
    history = data.get('messages')
    if not isinstance(history, list) or not history:
        return _error('No messages sent.', 400)
    emotion = data.get('emotion') if isinstance(data.get('emotion'), str) else None
    try:
        result = chat_reply(history, emotion)
    except RuntimeError as e:          # missing API key
        return _error(str(e), 503)
    except Exception as e:
        if _is_quota_error(e):
            log.warning('Claude chat skipped: API quota exhausted (429)')
            return _error(QUOTA_MESSAGE, 429)
        log.exception('Claude chat failed')
        return _error("The AI service isn't responding right now. Please try again in a moment.", 502)

    # Signed-in patients: alert their family on signs of a crisis, panic attack or meltdown.
    # Family see only the type of alert, never the chat text.
    result['alert_sent'] = False
    user = g.get('user')
    if user is not None and user.role == 'patient':
        last_user = next((str(m.get('text', '')) for m in reversed(history)
                          if isinstance(m, dict) and m.get('role') != 'model'), '')
        kind = 'crisis' if result.get('crisis') else detect_urgent(last_user)
        if kind and alert_from_chat(user, kind):
            result['alert_sent'] = True
    return jsonify(result)


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
    source = 'voice' if data.get('source') == 'voice' else 'chat'
    try:
        emotion = detect_emotion(base64.b64decode(b64), mime_type)
    except NoFaceDetected:
        return jsonify(emotion=None, saved=False)
    except RuntimeError as e:
        return _error(str(e), 503)
    except Exception as e:
        if _is_quota_error(e):
            log.warning('Claude emotion detection skipped: API quota exhausted (429)')
            return _error(QUOTA_MESSAGE, 429)
        log.exception('Claude emotion detection failed')
        return _error('Emotion detection failed.', 502)
    return jsonify(emotion=emotion, saved=_record_expression(emotion, source))


def _record_expression(emotion, source):
    """Save a reading if the signed-in user opted in. Always prints it in the terminal for the demo."""
    user = g.get('user')
    if not (user and user.save_expressions):
        log.info('EXPRESSION  %-8s via %-5s  (guest or not opted in - not saved)', emotion, source)
        return False
    reading = ExpressionReading(user_id=user.id, emotion=emotion, source=source)
    db.session.add(reading)
    db.session.commit()
    log.info('EXPRESSION  %-8s via %-5s  saved for user %s (%s)', emotion, source, user.id, user.name)
    try:
        new_file = not os.path.exists(EXPRESSION_LOG)
        with open(EXPRESSION_LOG, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if new_file:
                writer.writerow(['time_utc', 'user_id', 'user_name', 'emotion', 'source'])
            writer.writerow([as_utc(reading.created_at).isoformat(timespec='seconds'), user.id, user.name, emotion, source])
    except OSError:
        log.exception('Could not write %s', EXPRESSION_LOG)
    return True


def _purge_expression_log(user_id):
    """Remove a user's rows from the CSV log, so deleting data really deletes it."""
    if not os.path.exists(EXPRESSION_LOG):
        return
    with open(EXPRESSION_LOG, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    keep = [r for r in rows if not (len(r) > 1 and r[1] == str(user_id))]
    with open(EXPRESSION_LOG, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerows(keep)


@app.post('/api/expressions/delete')
@login_required
def api_delete_expressions():
    """Delete all of the user's saved expression readings (keeps the account)."""
    ExpressionReading.query.filter_by(user_id=g.user.id).delete()
    db.session.commit()
    _purge_expression_log(g.user.id)
    return jsonify(deleted=True)


def _rating(value):
    if value is None or value == '':
        return None
    value = int(value)
    if not 0 <= value <= 10:
        raise ValueError
    return value


@app.route('/api/checkins', methods=['GET', 'POST'])
@roles_required('patient')
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
@roles_required('patient', 'provider', 'family')
def api_delete_me():
    """Delete the account and everything tied to it. Required for user control over their data."""
    user_id = g.user.id
    delete_user_everywhere(g.user)
    _purge_expression_log(user_id)
    session.clear()
    return jsonify(deleted=True)


if __name__ == '__main__':
    app.run(debug=True)
