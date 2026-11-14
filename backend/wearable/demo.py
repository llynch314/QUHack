"""Demo console (DEMO_MODE=1 and DEV_LOGIN=1 only, from this laptop only).

A separate page, outside the app, that drives a patient's simulated watch and shows side by side
what the patient, their family and their doctor each get. The real app windows react live.
The console can drive the built-in Demo Patient or any real patient account (e.g. someone who
signed in with Google for the demo).

  /demo                     the console page
  /api/demo/patients        patient accounts the console can drive
  /api/demo/overview        what each person sees right now          (?patient_id=, default Demo Patient)
  /api/demo/scenario        play a scenario (baseline, exercise, ...)  {"scenario", "patient_id"}
  /api/demo/action          act as the patient or family               {"action", "patient_id"}
  /api/demo/settings        the patient's "who gets told what" switches
  /api/demo/link-team       put the demo family member + doctor on this patient's care team
  /api/demo/reset           clear this patient's watch data, alerts and reports
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


class NotReady(Exception):
    pass


@bp.before_request
def _guard():
    """Never reachable in production or through the tunnel: DEMO_MODE + DEV_LOGIN, local requests only."""
    if not (demo_mode() and os.getenv('DEV_LOGIN') == '1'):
        abort(404)
    proxied = any(request.headers.get(h) for h in ('X-Forwarded-For', 'X-Forwarded-Proto', 'CF-Connecting-IP'))
    if request.remote_addr not in LOOPBACK or proxied:
        abort(404)


@bp.errorhandler(NotReady)
def _not_ready(e):
    return jsonify(error=str(e), consent_required=True), 409


def _is_demo(user):
    return user.google_sub == integrations.DEMO_PATIENT_SUB


def _requested_id():
    raw = request.args.get('patient_id')
    if raw is None and request.is_json:
        raw = (request.get_json(silent=True) or {}).get('patient_id')
    try:
        return int(raw) if raw not in (None, '') else None
    except (TypeError, ValueError):
        abort(400, 'patient_id must be a number')


def _patient(require_consent=False):
    """The patient this request is about. Default: the built-in Demo Patient (care team + consent set up)."""
    pid = _requested_id()
    if pid is None:
        patient = integrations.demo_user('patient')
    else:
        patient = db.session.get(User, pid)
        if patient is None or patient.role != 'patient':
            abort(404, 'No patient account with that id.')
    if _is_demo(patient):
        for role in ('family', 'provider'):
            integrations.demo_user(role)
        profile = service.ensure_profile(patient.id)
        if profile.consent_version != CONSENT_VERSION:
            profile.consent_version, profile.consent_at = CONSENT_VERSION, utcnow()
            db.session.commit()
    elif require_consent and service.ensure_profile(patient.id).consent_version != CONSENT_VERSION:
        # A real account: they accept the watch consent themselves, on their own My Watch page.
        raise NotReady(f'{patient.display_name} has not accepted the My Watch consent yet. Open My Watch '
                       'signed in as them and click "I understand and agree".')
    return patient


def _audit(action, patient_id, resource=None):
    audit(action, patient_id, resource=resource, actor_role='demo-console')


def _port():
    return request.host.rsplit(':', 1)[1] if ':' in request.host else '80'


def _members(patient_id, role):
    return [u.display_name for u in User.query.join(CareLink, CareLink.member_id == User.id)
            .filter(CareLink.patient_id == patient_id, User.role == role)]


def _apps(patient):
    """Links that open each person's app. Demo accounts get their own *.localhost address, so the
    browser keeps a separate sign-in for each; a real (Google) patient uses the normal address."""
    port = _port()
    if _is_demo(patient):
        p = {'url': f'http://patient.localhost:{port}/wearable/dev-login/patient',
             'fallback': f'http://127.0.0.1:{port}/wearable/dev-login/patient',
             'hint': 'Signs in as Demo Patient.'}
    else:
        p = {'url': f'http://127.0.0.1:{port}/wearable', 'fallback': None,
             'hint': f'Sign in there with {patient.email or "their Google account"} (Patient sign-in).'}
    q = f'?patient={patient.id}'
    return {
        'patient': p,
        'family': {'url': f'http://family.localhost:{port}/wearable/dev-login/family{q}',
                   'fallback': f'http://127.0.0.1:{port}/wearable/dev-login/family{q}',
                   'hint': 'Signs in as Demo Family member.'},
        'doctor': {'url': f'http://doctor.localhost:{port}/wearable/dev-login/provider{q}',
                   'fallback': f'http://127.0.0.1:{port}/wearable/dev-login/provider{q}',
                   'hint': 'Signs in as the demo doctor (Demo Clinic).'},
    }


@bp.route('/demo')
def page():
    _patient()   # make sure the built-in demo accounts exist
    return render_template('wearable_demo.html', scenarios=simulator.SCENARIOS)


@bp.get('/api/demo/patients')
def patients():
    integrations.demo_user('patient')
    rows = User.query.filter_by(role='patient').order_by(User.id.desc()).all()
    out = []
    for u in rows:
        profile = service.ensure_profile(u.id)
        out.append({'id': u.id, 'name': u.display_name, 'email': u.email, 'demo': _is_demo(u),
                    'consent': _is_demo(u) or profile.consent_version == CONSENT_VERSION,
                    'family': _members(u.id, 'family'), 'doctors': _members(u.id, 'provider')})
    out.sort(key=lambda p: p['demo'])   # real (Google) patients first
    return jsonify(patients=out)


@bp.get('/api/demo/overview')
def overview():
    patient = _patient()
    pid = patient.id
    live = service.latest_state(pid)       # also sends fall alerts whose countdown ended
    alerts = Alert.query.filter_by(patient_id=pid).order_by(Alert.id.desc()).limit(8).all()
    reports = integrations.reports_for([pid], limit=6)
    profile = service.ensure_profile(pid)
    return jsonify(
        patient={'id': pid, 'name': patient.display_name, 'email': patient.email, 'demo': _is_demo(patient),
                 'consent': profile.consent_version == CONSENT_VERSION},
        apps=_apps(patient),
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
    pid = _patient(require_consent=True).id
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
    pid = _patient(require_consent=True).id
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


@bp.post('/api/demo/link-team')
def link_team():
    """Demo shortcut for what the patient would do on their Care Team page: add the demo family
    member and the demo doctor (by email), so alerts and reports have someone to go to."""
    pid = _patient().id
    added = []
    for role in ('family', 'provider'):
        member = integrations.demo_user(role)
        if not CareLink.query.filter_by(patient_id=pid, member_id=member.id).first():
            db.session.add(CareLink(patient_id=pid, member_id=member.id))
            added.append(member.display_name)
    db.session.commit()
    _audit('write_care_team', pid, 'demo-console')
    return jsonify(added=added, family=_members(pid, 'family'), doctors=_members(pid, 'provider'))


@bp.post('/api/demo/reset')
def reset():
    pid = _patient().id
    counts = service.delete_all(pid, keep_profile=True, keep_devices=True)
    _audit('write_demo_reset', pid)
    return jsonify(reset=True, deleted=counts)
