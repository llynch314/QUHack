"""Wearable endpoints (PRD §6.5) plus the patient / family / provider pages."""
import base64
import io
import json
import logging
import os
from functools import wraps

from flask import (Blueprint, Response, abort, g, jsonify, redirect, render_template, request, session, url_for)

from models import User, db

from . import escalation, integrations, service, simulator
from .models import CONSENT_VERSION, _iso, WearableAlert, WearableDevice, WearableNudge
from .security import (MAX_INGEST_BYTES, audit, check_idle, demo_mode, hash_token, https_rejection, ingest_limiter,
                       new_device_token, request_is_secure, transport_allowed, utcnow)

log = logging.getLogger('mindconnect.wearable')
bp = Blueprint('wearable', __name__)

SYMPTOMS = ('chest_pain', 'cant_breathe', 'fainting', 'panic')
CORRECTIONS = ('exercising', 'not_okay', 'im_ok')


def _err(message, status, **extra):
    return jsonify(error=message, **extra), status


# ---------- request guards ----------

@bp.before_request
def _guard():
    if not transport_allowed():
        log.info('wearable: rejected non-HTTPS request path=%s', request.path)
        return https_rejection()
    if request.endpoint == 'wearable.ingest':
        return None   # device-token auth, no session
    if check_idle():
        if request.path.startswith('/api/'):
            return _err('Signed out after inactivity to protect your health data. Please sign in again.', 401,
                        reauth=True)
        return redirect(url_for('auth.login', next=request.path))
    return None


@bp.after_request
def _headers(resp):
    if request_is_secure():
        resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Referrer-Policy'] = 'same-origin'
    if request.path.startswith('/api/'):
        resp.headers['Cache-Control'] = 'no-store'
    return resp


def signed_in(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get('user') is None:
            if request.path.startswith('/api/'):
                return _err('Please sign in first.', 401)
            return redirect(url_for('auth.login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def patient_only(view):
    @wraps(view)
    @signed_in
    def wrapped(*args, **kwargs):
        if integrations.get_role(g.user) != 'patient':
            audit(f'denied:{request.endpoint}', None, outcome='denied', resource=request.path)
            return _err('Only the patient can do this.', 403)
        return view(*args, **kwargs)
    return wrapped


def _vitals_guard(patient_id, action):
    if not integrations.can_view_vitals(g.user, patient_id):
        audit(action, patient_id, outcome='denied', resource=request.path)
        return _err("You don't have access to this patient's vitals.", 403)
    audit(action, patient_id, resource=request.path)
    return None


def _consented(patient_id):
    p = service.ensure_profile(patient_id)
    return p.consent_version == CONSENT_VERSION


def _base_url():
    base = (os.getenv('PUBLIC_BASE_URL') or '').rstrip('/')
    if base:
        return base
    url = request.host_url.rstrip('/')
    if request_is_secure() and url.startswith('http://'):
        url = 'https://' + url[len('http://'):]
    return url


# ---------- pages ----------

@bp.route('/wearable')
@signed_in
def page():
    role = integrations.get_role(g.user)
    if role == 'family':      # family see watch alerts on the team's Alerts page
        return redirect(url_for('care.family_home'))
    if role == 'provider':    # providers see watch reports as health documents on My Patients
        return redirect(url_for('care.provider_home'))
    return render_template('wearable.html', demo_mode=demo_mode(), patient_id=g.user.id,
                           consent_version=CONSENT_VERSION)


@bp.route('/wearable/dev-login/<role>')
def dev_login(role):
    """DEV_LOGIN=1 only. One click to become the demo patient, family member or provider.
    Uses the same demo accounts as the normal sign-in (/login?role=...), but skips the consent
    screen and links family + provider to the demo patient's care team, so every view works at once."""
    if os.getenv('DEV_LOGIN') != '1' or role not in integrations.ROLES:
        abort(404)
    for r in ('family', 'provider'):   # the demo care team always exists, whoever signs in first
        integrations.demo_user(r)
    user = integrations.demo_user(role)
    session.clear()
    session['user_id'] = user.id
    session.permanent = True
    if role == 'family':
        return redirect(url_for('care.family_home'))
    if role == 'provider':
        # ?patient=<id> (from the demo console): open that patient's documents if they added this doctor
        target = request.args.get('patient', type=int)
        if not (target and integrations.can_view_reports(user, target)):
            target = integrations.demo_user('patient').id
        return redirect(url_for('care.provider_patient', patient_id=target))
    return redirect(url_for('wearable.page'))


# ---------- consent & settings ----------

@bp.get('/api/wearable/config')
@signed_in
def config():
    return jsonify(demo_mode=demo_mode(), role=integrations.get_role(g.user), user_id=g.user.id,
                   ingest_url=_base_url() + '/api/wearable/ingest', secure=request_is_secure(),
                   scenarios=simulator.SCENARIOS, consent_version=CONSENT_VERSION)


@bp.post('/api/wearable/consent')
@patient_only
def consent():
    data = request.get_json(silent=True) or {}
    if data.get('accept') is not True:
        return _err('Consent must be accepted explicitly.', 400)
    p = service.ensure_profile(g.user.id)
    p.consent_version, p.consent_at = CONSENT_VERSION, utcnow()
    db.session.commit()
    audit('write_consent', g.user.id)
    return jsonify(profile=p.to_dict())


@bp.route('/api/wearable/profile', methods=['GET', 'POST'])
@patient_only
def profile():
    p = service.ensure_profile(g.user.id)
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        for key in ('family_tier2_alerts', 'emergency_alerts', 'ai_explanations'):
            if key in data:
                if not isinstance(data[key], bool):
                    return _err(f'{key} must be true or false.', 400)
                setattr(p, key, data[key])
        for key, lo, hi in (('baseline_resting_hr', 35, 120), ('baseline_hrv', 5, 200)):
            if key in data:
                try:
                    v = float(data[key])
                except (TypeError, ValueError):
                    return _err(f'{key} must be a number.', 400)
                if not lo <= v <= hi:
                    return _err(f'{key} must be between {lo} and {hi}.', 400)
                setattr(p, key, v)
        db.session.commit()
        audit('write_profile', g.user.id)
    return jsonify(profile=p.to_dict())


# ---------- devices ----------

def _qr_data_uri(text):
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buf = io.BytesIO()
    img.save(buf)
    return 'data:image/svg+xml;base64,' + base64.b64encode(buf.getvalue()).decode()


@bp.route('/api/wearable/devices', methods=['GET', 'POST'])
@patient_only
def devices():
    if request.method == 'GET':
        audit('read_devices', g.user.id)
        rows = WearableDevice.query.filter_by(patient_id=g.user.id).order_by(WearableDevice.id.desc())
        return jsonify(devices=[d.to_dict() for d in rows])
    if not _consented(g.user.id):
        return _err('Please review and accept the wearable consent first.', 403, consent_required=True)
    data = request.get_json(silent=True) or {}
    label = (str(data.get('label') or 'My Apple Watch')).strip()[:80]
    source = data.get('source') if data.get('source') in ('apple_watch', 'simulator', 'other') else 'apple_watch'
    token, token_hash = new_device_token()
    device = WearableDevice(patient_id=g.user.id, token_hash=token_hash, label=label, source=source)
    db.session.add(device)
    db.session.commit()
    audit('write_device_create', g.user.id, resource=f'device:{device.id}')
    return jsonify(device=device.to_dict(), token=token, qr=_qr_data_uri(token),
                   ingest_url=_base_url() + '/api/wearable/ingest',
                   note='This token is shown once. Copy it into your iPhone Shortcut now.'), 201


@bp.delete('/api/wearable/devices/<int:device_id>')
@patient_only
def revoke_device(device_id):
    device = WearableDevice.query.filter_by(id=device_id, patient_id=g.user.id).first()
    if device is None:
        return _err('Device not found.', 404)
    if device.revoked_at is None:
        device.revoked_at = utcnow()
        db.session.commit()
    audit('write_device_revoke', g.user.id, resource=f'device:{device.id}')
    return jsonify(device=device.to_dict())


# ---------- ingest (device token) ----------

@bp.post('/api/wearable/ingest')
def ingest():
    if request.content_length is not None and request.content_length > MAX_INGEST_BYTES:
        return _err('Payload too large.', 413)
    token = (request.headers.get('X-Device-Token') or '').strip()
    device = WearableDevice.query.filter_by(token_hash=hash_token(token)).first() if token else None
    if device is None or device.revoked_at is not None:
        audit('write_ingest', device.patient_id if device else None, outcome='denied',
              resource=f'device:{device.id}' if device else 'device:unknown', actor_role='device')
        return _err('Invalid or revoked device token.', 401)
    if not ingest_limiter.allow(device.id):
        return _err('Too many requests from this device. Try again in a minute.', 429)
    if not _consented(device.patient_id):
        return _err('The patient has not accepted the wearable consent yet.', 403, consent_required=True)
    raw = request.get_data(cache=True)
    if len(raw) > MAX_INGEST_BYTES:
        return _err('Payload too large.', 413)
    try:
        data = json.loads(raw or b'null')
    except ValueError:
        return _err('Body must be valid JSON.', 400)
    try:
        result = service.ingest(device.patient_id, data, source=None)
    except service.PayloadError as e:
        return _err(str(e), 400)
    device.last_seen_at = utcnow()
    db.session.commit()
    audit('write_ingest', device.patient_id, resource=f'device:{device.id}', actor_role='device')
    return jsonify(state=result['state'], alert=result['alert'], inserted=result['inserted'],
                   duplicates=result['duplicates'])


# ---------- patient reads ----------

@bp.get('/api/patients/<int:patient_id>/state')
@signed_in
def state(patient_id):
    denied = _vitals_guard(patient_id, 'read_state')
    if denied:
        return denied
    out = service.latest_state(patient_id)
    out['plan'] = service.resolution_plan(patient_id, out['state'])
    return jsonify(out)


@bp.get('/api/patients/<int:patient_id>/vitals')
@signed_in
def vitals(patient_id):
    denied = _vitals_guard(patient_id, 'read_vitals')
    if denied:
        return denied
    return jsonify(service.timeline(patient_id, request.args.get('range', '24h')))


# ---------- patient actions ----------

@bp.post('/api/wearable/feedback')
@patient_only
def feedback():
    correction = (request.get_json(silent=True) or {}).get('correction')
    if correction not in CORRECTIONS:
        return _err(f'correction must be one of: {", ".join(CORRECTIONS)}', 400)
    result = service.add_patient_event(g.user.id, correction)
    audit('write_feedback', g.user.id, resource=correction)
    return jsonify(result)


@bp.post('/api/wearable/emergency/call')
@patient_only
def emergency_call():
    """The patient tapped Call 911 on the emergency screen. The phone dials 911 itself (tel: link);
    here we skip the "I'm OK" countdown and alert family right away. In DEMO_MODE no call is made."""
    sent = escalation.send_now(g.user.id)
    audit('write_emergency_call', g.user.id)
    return jsonify(family_alerted=sent, family_count=integrations.family_count(g.user.id), demo_mode=demo_mode())


@bp.post('/api/wearable/self-report')
@patient_only
def self_report():
    symptom = (request.get_json(silent=True) or {}).get('symptom')
    if symptom not in SYMPTOMS:
        return _err(f'symptom must be one of: {", ".join(SYMPTOMS)}', 400)
    result = service.add_patient_event(g.user.id, 'self_report', {'symptom': symptom})
    audit('write_self_report', g.user.id)
    return jsonify(result)


@bp.post('/api/wearable/nudges/<int:nudge_id>/seen')
@patient_only
def nudge_seen(nudge_id):
    n = WearableNudge.query.filter_by(id=nudge_id, patient_id=g.user.id).first()
    if n is None:
        return _err('Not found.', 404)
    n.seen_at = n.seen_at or utcnow()
    db.session.commit()
    return jsonify(nudge=n.to_dict())


# ---------- demo (DEMO_MODE=1 only) ----------

@bp.post('/api/wearable/demo/scenario')
@patient_only
def demo_scenario():
    if not demo_mode():
        abort(404)
    scenario = (request.get_json(silent=True) or {}).get('scenario')
    if scenario not in simulator.SCENARIOS:
        return _err(f'scenario must be one of: {", ".join(simulator.SCENARIOS)}', 400)
    if not _consented(g.user.id):
        return _err('Please review and accept the wearable consent first.', 403, consent_required=True)
    result = service.run_scenario(g.user.id, scenario)
    audit('write_demo_scenario', g.user.id, resource=scenario)
    return jsonify(scenario=scenario, **result)


@bp.post('/api/wearable/demo/reset')
@patient_only
def demo_reset():
    if not demo_mode():
        abort(404)
    counts = service.delete_all(g.user.id, keep_profile=True, keep_devices=True)
    audit('write_demo_reset', g.user.id)
    return jsonify(reset=True, deleted=counts)


# ---------- reports (patient + linked provider) ----------

@bp.post('/api/patients/<int:patient_id>/wearable-report')
@patient_only
def make_report(patient_id):
    if patient_id != g.user.id:
        audit('write_report', patient_id, outcome='denied')
        return _err('You can only generate your own report.', 403)
    rep = service.generate_report(patient_id)
    audit('write_report', patient_id, resource=f'report:{rep.id}')
    return jsonify(report=_report_json(rep)), 201


def _report_json(rep, with_body=True):
    out = {'id': rep.id, 'patient_id': rep.patient_id, 'title': rep.title, 'category': rep.category,
           'created_at': _iso(rep.created_at)}
    if with_body:
        out['body'] = rep.body
    return out


def _report_patients():
    role = integrations.get_role(g.user)
    if role == 'patient':
        return [g.user.id]
    if role == 'provider':
        return integrations.linked_patient_ids(g.user, 'provider')
    return []


@bp.get('/api/wearable/reports')
@signed_in
def list_reports():
    ids = _report_patients()
    if not ids:
        audit('read_reports', None, outcome='denied', resource=request.path)
        return _err('Only the patient and their providers can read wearable reports.', 403)
    rows = integrations.reports_for(ids)
    names = {u.id: u.display_name for u in User.query.filter(User.id.in_(ids))}
    for pid in ids:
        audit('read_reports', pid)
    return jsonify(reports=[{**_report_json(r, with_body=False), 'patient_name': names.get(r.patient_id)}
                            for r in rows])


@bp.get('/api/wearable/reports/<int:report_id>')
@signed_in
def get_report(report_id):
    rep = integrations.get_report(report_id)
    if rep is None:
        return _err('Not found.', 404)
    if not integrations.can_view_reports(g.user, rep.patient_id):
        audit('read_report', rep.patient_id, outcome='denied', resource=f'report:{rep.id}')
        return _err("You don't have access to this report.", 403)
    audit('read_report', rep.patient_id, resource=f'report:{rep.id}')
    return jsonify(report=_report_json(rep))


# ---------- alerts (family + patient; providers never) ----------

@bp.get('/api/wearable/alerts')
@signed_in
def list_alerts():
    escalation.promote_due_alerts()
    role = integrations.get_role(g.user)
    if role == 'family':
        ids = integrations.linked_patient_ids(g.user, 'family')
    elif role == 'patient':
        ids = [g.user.id]
    else:
        audit('read_alerts', None, outcome='denied', resource=request.path)
        return _err('Providers receive reports, not live alerts.', 403)
    q = WearableAlert.query.filter(WearableAlert.patient_id.in_(ids), WearableAlert.status.in_(('open', 'acknowledged')))
    if request.args.get('unacknowledged') == '1':
        q = q.filter(WearableAlert.status == 'open')
    rows = q.order_by(WearableAlert.id.desc()).limit(50).all()
    if any([integrations.sync_ack(a) for a in rows]):
        db.session.commit()
        rows = [a for a in rows if request.args.get('unacknowledged') != '1' or a.status == 'open']
    names = {u.id: u.display_name for u in User.query.filter(User.id.in_(ids))} if ids else {}
    for pid in ids:
        audit('read_alerts', pid)
    return jsonify(alerts=[{**a.to_dict(), 'patient_name': names.get(a.patient_id)} for a in rows])


@bp.post('/api/wearable/alerts/<int:alert_id>/ack')
@signed_in
def ack_alert(alert_id):
    a = db.session.get(WearableAlert, alert_id)
    if a is None or not integrations.can_view_alerts(g.user, a.patient_id):
        audit('write_alert_ack', a.patient_id if a else None, outcome='denied')
        return _err('Not found.', 404)
    integrations.acknowledge(a, g.user)
    audit('write_alert_ack', a.patient_id, resource=f'alert:{a.id}')
    return jsonify(alert=a.to_dict())


# ---------- privacy panel ----------

@bp.get('/api/wearable/privacy')
@patient_only
def privacy():
    audit('read_privacy', g.user.id)
    return jsonify(service.privacy_summary(g.user.id))


@bp.get('/api/wearable/export')
@patient_only
def export():
    audit('export', g.user.id)
    body = json.dumps(service.export_data(g.user.id), indent=2)
    return Response(body, mimetype='application/json',
                    headers={'Content-Disposition': 'attachment; filename="attunemind-wearable-export.json"'})


@bp.post('/api/wearable/delete')
@patient_only
def delete_data():
    if (request.get_json(silent=True) or {}).get('confirm') != 'DELETE':
        return _err('Send {"confirm": "DELETE"} to delete your wearable data.', 400)
    counts = service.delete_all(g.user.id)
    audit('delete_all_wearable_data', g.user.id, resource=json.dumps(counts)[:80])
    return jsonify(deleted=counts)
