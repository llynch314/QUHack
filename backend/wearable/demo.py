"""Demo console (DEMO_MODE=1 and DEV_LOGIN=1 only, from this laptop only).

A separate page, outside the app, that drives the demo patient's simulated watch and shows
side by side what the patient, their family and their doctor each get. The real app windows
(patient / family / doctor) react to it live.

  /demo                     the console page
  /api/demo/overview        what each person sees right now
  /api/demo/scenario        play a scenario (baseline, exercise, stress_spike, ...)
  /api/demo/action          act as the patient or family (I'm OK, Call 911, acknowledge, ...)
  /api/demo/settings        the patient's "who gets told what" switches
  /api/demo/reset           clear the demo patient's watch data, alerts and reports
"""
import os

from flask import Blueprint, abort, jsonify, render_template, request

from models import Alert, CareLink, User, _now, db

from . import escalation, integrations, service, simulator
from .models import CONSENT_VERSION, _iso
from .security import LOOPBACK, audit, demo_mode, utcnow

bp = Blueprint('wearable_demo', __name__)

ACTIONS = ('im_ok', 'call_911', 'exercising', 'not_okay', 'chest_pain', 'family_ack')
SETTINGS = ('family_tier2_alerts', 'emergency_alerts')
APPS = (('patient', 'Patient', '/wearable/dev-login/patient'),
        ('family', 'Family', '/wearable/dev-login/family'),
        ('doctor', 'Doctor', '/wearable/dev-login/provider'))


@bp.before_request
def _guard():
    """Never reachable in production or through the tunnel: DEMO_MODE + DEV_LOGIN, local requests only."""
    if not (demo_mode() and os.getenv('DEV_LOGIN') == '1'):
        abort(404)
    proxied = any(request.headers.get(h) for h in ('X-Forwarded-For', 'X-Forwarded-Proto', 'CF-Connecting-IP'))
    if request.remote_addr not in LOOPBACK or proxied:
        abort(404)


def _patient():
    """The demo patient, with the demo family member + doctor on their care team and consent done."""
    patient = integrations.demo_user('patient')
    for role in ('family', 'provider'):
        integrations.demo_user(role)
    profile = service.ensure_profile(patient.id)
    if profile.consent_version != CONSENT_VERSION:
        profile.consent_version, profile.consent_at = CONSENT_VERSION, utcnow()
        db.session.commit()
    return patient


def _audit(action, patient_id, resource=None):
    audit(action, patient_id, resource=resource, actor_role='demo-console')


def _app_links():
    port = request.host.rsplit(':', 1)[1] if ':' in request.host else '80'
    return [{'key': key, 'label': label,
             'url': f'http://{key}.localhost:{port}{path}',          # own address = own sign-in
             'fallback': f'http://127.0.0.1:{port}{path}'} for key, label, path in APPS]


@bp.route('/demo')
def page():
    _patient()
    return render_template('wearable_demo.html', apps=_app_links(), scenarios=simulator.SCENARIOS)


def _members(patient_id, role):
    return [u.display_name for u in User.query.join(CareLink, CareLink.member_id == User.id)
            .filter(CareLink.patient_id == patient_id, User.role == role)]


@bp.get('/api/demo/overview')
def overview():
    patient = _patient()
    pid = patient.id
    live = service.latest_state(pid)       # also sends fall alerts whose countdown ended
    alerts = Alert.query.filter_by(patient_id=pid).order_by(Alert.id.desc()).limit(8).all()
    reports = integrations.reports_for([pid], limit=6)
    profile = service.ensure_profile(pid)
    return jsonify(
        patient={'id': pid, 'name': patient.display_name},
        state=live['state'], latest=live['latest'], nudge=live['nudge'],
        pending_alert=live['pending_alert'], server_time=live['server_time'],
        settings={k: getattr(profile, k) for k in SETTINGS},
        family={'members': _members(pid, 'family'), 'alerts': [a.to_dict() for a in alerts]},
        doctor={'members': _members(pid, 'provider'),
                'reports': [{'id': r.id, 'title': r.title, 'created_at': _iso(r.created_at), 'body': r.body}
                            for r in reports]},
    )


@bp.post('/api/demo/scenario')
def scenario():
    name = (request.get_json(silent=True) or {}).get('scenario')
    if name not in simulator.SCENARIOS:
        return jsonify(error=f'scenario must be one of: {", ".join(simulator.SCENARIOS)}'), 400
    pid = _patient().id
    reports_before = len(integrations.reports_for([pid], limit=1000))
    result = service.run_scenario(pid, name)
    _audit('write_demo_scenario', pid, name)
    return jsonify(scenario=name, state=result['state'], alert=result['alert'],
                   report_created=len(integrations.reports_for([pid], limit=1000)) > reports_before)


@bp.post('/api/demo/action')
def action():
    act = (request.get_json(silent=True) or {}).get('action')
    if act not in ACTIONS:
        return jsonify(error=f'action must be one of: {", ".join(ACTIONS)}'), 400
    pid = _patient().id
    out = {'action': act}
    if act == 'call_911':
        out['family_alerted'] = escalation.send_now(pid)
    elif act == 'family_ack':
        a = Alert.query.filter_by(patient_id=pid, acknowledged_at=None).order_by(Alert.id.desc()).first()
        if a is not None:
            a.acknowledged_at, a.acknowledged_by = _now(), integrations.demo_user('family').display_name
            db.session.commit()
        out['acknowledged'] = a is not None
    elif act == 'chest_pain':
        out.update(service.add_patient_event(pid, 'self_report', {'symptom': 'chest_pain'}))
    else:
        out.update(service.add_patient_event(pid, act))
    _audit('write_demo_action', pid, act)
    return jsonify(out)


@bp.post('/api/demo/settings')
def settings():
    data = request.get_json(silent=True) or {}
    pid = _patient().id
    profile = service.ensure_profile(pid)
    for key in SETTINGS:
        if key in data:
            setattr(profile, key, bool(data[key]))
    db.session.commit()
    _audit('write_profile', pid, 'demo-console')
    return jsonify(settings={k: getattr(profile, k) for k in SETTINGS})


@bp.post('/api/demo/reset')
def reset():
    pid = _patient().id
    counts = service.delete_all(pid, keep_profile=True, keep_devices=True)
    _audit('write_demo_reset', pid)
    return jsonify(reset=True, deleted=counts)
