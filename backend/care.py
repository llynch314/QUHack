"""Care team, health documents and urgent alerts: the patient / provider / family features.

  Patient  : manages their care team, documents and alerts (Care Team page)
  Provider : sees and adds health documents for patients who added them (My Patients page)
  Family   : sees and acknowledges urgent alerts for patients who added them (Alerts page),
             and can get them by text message too (see sms.py)
"""
from datetime import timedelta

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request,
                   url_for)

from auth import require_access, roles_required
import sms
from models import (ALERT_KINDS, ALERT_LABELS, Alert, CareLink, HealthDocument, PhoneVerification, User,
                    _now, as_utc, db)
from safety import ALERT_NOTES

bp = Blueprint('care', __name__)

ALERT_COOLDOWN = timedelta(minutes=10)   # don't send the same chat alert over and over


def _json():
    return request.get_json(silent=True) or {}


def _links_for(user):
    if user.role == 'patient':
        return CareLink.query.filter_by(patient_id=user.id).order_by(CareLink.created_at).all()
    return CareLink.query.filter_by(member_id=user.id).order_by(CareLink.created_at).all()


def _profile_redirect():
    """Providers without a profile are sent to fill it in first (patients need to know who they are)."""
    if g.user.needs_profile:
        flash('Please add where you work before viewing patients.')
        return redirect(url_for('auth.account', next=request.path))
    return None


def _author_name(user):
    """How a document's author is shown, e.g. 'Dr Lee, Psychiatrist, City Hospital (Health provider)'."""
    details = ', '.join(p for p in (user.display_name, user.provider_summary) if p)
    return f'{details} ({user.role_label})'


def create_alert(patient, kind, source, note=''):
    alert = Alert(patient_id=patient.id, kind=kind, source=source, note=(note or '')[:500])
    db.session.add(alert)
    db.session.commit()
    text_family(alert)
    return alert


def text_family(alert):
    """Text every linked family member who confirmed a phone number and kept text alerts on."""
    family = (User.query.join(CareLink, CareLink.member_id == User.id)
              .filter(CareLink.patient_id == alert.patient_id, User.role == 'family',
                      User.phone.isnot(None), User.sms_alerts.is_(True)).all())
    if not family:
        return 0
    body = sms.alert_text(alert.patient.display_name, ALERT_LABELS.get(alert.kind, alert.kind),
                          url_for('care.family_home', _external=True))
    sms.dispatch([(member.phone, body) for member in family])
    return len(family)


def alert_from_chat(patient, kind):
    """Called by /api/chat. Returns the new alert, or None if alerts are off or one was just sent."""
    if not patient.auto_alerts:
        return None
    recent = Alert.query.filter(Alert.patient_id == patient.id, Alert.kind == kind,
                                Alert.source == 'chat',
                                Alert.created_at >= _now() - ALERT_COOLDOWN).first()
    if recent:
        return None
    return create_alert(patient, kind, 'chat', ALERT_NOTES[kind])


# ---------- Pages ----------

@bp.route('/care-team')
@roles_required('patient')
def care_team_page():
    """Old Care Team page; now the Care Team tab of the patient app (frontend/test.html)."""
    return redirect(url_for('test_dashboard') + '#care-team')


@bp.route('/provider')
@roles_required('provider')
def provider_home():
    return _profile_redirect() or render_template('provider.html', links=_links_for(g.user))


@bp.route('/provider/patients/<int:patient_id>')
@roles_required('provider')
def provider_patient(patient_id):
    if (r := _profile_redirect()):
        return r
    require_access(patient_id, 'documents')
    patient = db.session.get(User, patient_id)
    docs = (HealthDocument.query.filter_by(patient_id=patient_id)
            .order_by(HealthDocument.created_at.desc()).all())
    return render_template('provider_patient.html', patient=patient, docs=docs)


@bp.route('/family')
@roles_required('family')
def family_home():
    return render_template('family.html', links=_links_for(g.user))


# ---------- Care team API ----------

@bp.get('/api/care-team')
@roles_required('patient', 'provider', 'family')
def api_list_links():
    """Patient: their care team. Provider/family: the patients who added them."""
    return jsonify(links=[l.to_dict() for l in _links_for(g.user)])


@bp.post('/api/care-team')
@roles_required('patient')
def api_add_member():
    email = (_json().get('email') or '').strip().lower()
    member = User.query.filter(db.func.lower(User.email) == email).first() if email else None
    if member is None:
        abort(404, 'No AttuneMIND account uses that email. Ask them to sign in once first, '
                   'using the provider or family sign-in.')
    if member.role not in ('provider', 'family'):
        abort(400, 'You can only add health providers and family members.')
    if CareLink.query.filter_by(patient_id=g.user.id, member_id=member.id).first():
        abort(409, "They're already on your care team.")
    link = CareLink(patient_id=g.user.id, member_id=member.id)
    db.session.add(link)
    db.session.commit()
    return jsonify(link=link.to_dict()), 201


@bp.delete('/api/care-team/<int:link_id>')
@roles_required('patient')
def api_remove_member(link_id):
    link = db.session.get(CareLink, link_id)
    if link is None or link.patient_id != g.user.id:
        abort(404, 'Not found.')
    db.session.delete(link)
    db.session.commit()
    return '', 204


@bp.patch('/api/me/settings')
@roles_required('patient')
def api_settings():
    data = _json()
    if 'auto_alerts' in data:
        g.user.auto_alerts = bool(data['auto_alerts'])
    if 'save_expressions' in data:            # opt-in to saving camera expression readings
        g.user.save_expressions = bool(data['save_expressions'])
        g.user.expressions_consent_at = _now()
    db.session.commit()
    return jsonify(auto_alerts=g.user.auto_alerts, save_expressions=g.user.save_expressions)


# ---------- Text-message alerts (family) ----------

def _phone_state(user):
    return {'phone': user.phone_masked, 'sms_alerts': user.sms_alerts, 'demo_mode': not sms.twilio_configured()}


@bp.get('/api/me/phone')
@roles_required('family')
def api_phone():
    return jsonify(_phone_state(g.user))


@bp.post('/api/me/phone')
@roles_required('family')
def api_phone_start():
    """Step 1: text a 6-digit code to the number."""
    phone = sms.normalize_phone(_json().get('phone'))
    if phone is None:
        abort(400, 'Please enter a full phone number, like 555-123-4567 (or +44 ... outside the US).')
    pending = PhoneVerification.query.filter_by(user_id=g.user.id).first()
    if pending and as_utc(pending.created_at) > _now() - sms.RESEND_WAIT:
        abort(429, 'A code was just sent. Please wait a minute before asking for another.')
    code, code_hash = sms.new_code()
    try:
        sms.send_sms(phone, f'Your AttuneMIND code is {code}. It expires in 10 minutes. '
                            f"If you didn't ask for this, you can ignore it.")
    except Exception:
        current_app.logger.exception('Could not send verification code')
        abort(502, "We couldn't text that number. Please check it and try again.")
    if pending:
        db.session.delete(pending)
        db.session.flush()
    db.session.add(PhoneVerification(user_id=g.user.id, phone=phone, code_hash=code_hash,
                                     expires_at=_now() + sms.CODE_TTL))
    db.session.commit()
    return jsonify(sent=True, demo_mode=not sms.twilio_configured())


@bp.post('/api/me/phone/verify')
@roles_required('family')
def api_phone_verify():
    """Step 2: check the code; the number is saved only if it matches."""
    pending = PhoneVerification.query.filter_by(user_id=g.user.id).first()
    if pending is None or as_utc(pending.expires_at) < _now():
        abort(400, 'That code has expired. Please ask for a new one.')
    if pending.attempts >= sms.MAX_ATTEMPTS:
        abort(429, 'Too many wrong codes. Please ask for a new one.')
    if not sms.code_matches(pending.code_hash, _json().get('code')):
        pending.attempts += 1
        db.session.commit()
        abort(400, "That code doesn't match. Please check the text and try again.")
    g.user.phone = pending.phone
    g.user.sms_alerts = True
    db.session.delete(pending)
    db.session.commit()
    return jsonify(_phone_state(g.user))


@bp.patch('/api/me/phone')
@roles_required('family')
def api_phone_settings():
    data = _json()
    if 'sms_alerts' in data:
        g.user.sms_alerts = bool(data['sms_alerts'])
    db.session.commit()
    return jsonify(_phone_state(g.user))


@bp.delete('/api/me/phone')
@roles_required('family')
def api_phone_remove():
    g.user.phone = None
    PhoneVerification.query.filter_by(user_id=g.user.id).delete()
    db.session.commit()
    return jsonify(_phone_state(g.user))


@bp.post('/api/me/phone/test')
@roles_required('family')
def api_phone_test():
    if not g.user.phone:
        abort(400, 'Add and confirm a phone number first.')
    try:
        sms.send_sms(g.user.phone, 'AttuneMIND test: text alerts are working. You will get a text like '
                                   'this if someone who added you to their care team needs support.')
    except Exception:
        current_app.logger.exception('Could not send test text')
        abort(502, "We couldn't send the test text. Please try again later.")
    return jsonify(sent=True, demo_mode=not sms.twilio_configured())


# ---------- Health documents API (patient + linked providers) ----------

@bp.get('/api/patients/<int:patient_id>/documents')
@roles_required('patient', 'provider')
def api_list_documents(patient_id):
    require_access(patient_id, 'documents')
    docs = (HealthDocument.query.filter_by(patient_id=patient_id)
            .order_by(HealthDocument.created_at.desc()).all())
    return jsonify(documents=[d.to_dict() for d in docs])


@bp.post('/api/patients/<int:patient_id>/documents')
@roles_required('patient', 'provider')
def api_create_document(patient_id):
    require_access(patient_id, 'documents')
    data = _json()
    title = (data.get('title') or '').strip()
    if not title:
        abort(400, 'Add a title.')
    doc = HealthDocument(patient_id=patient_id, author_id=g.user.id,
                         author_name=_author_name(g.user),
                         title=title[:200], category=(data.get('category') or 'note').strip()[:50],
                         body=(data.get('body') or '')[:20000])
    db.session.add(doc)
    db.session.commit()
    return jsonify(document=doc.to_dict()), 201


@bp.post('/api/documents/progress-report')
@roles_required('patient')
def api_progress_report():
    """Patient chooses to save a snapshot of their check-in progress as a health document,
    so the providers on their care team can see it."""
    checkins = g.user.checkins
    if not checkins:
        abort(400, 'No check-ins yet. Try an exercise in the Calm Toolkit first.')
    rated = [c for c in checkins if c.stress_before is not None and c.stress_after is not None]
    lines = [f'{len(checkins)} check-ins.']
    if rated:
        avg = sum(c.stress_after - c.stress_before for c in rated) / len(rated)
        lines.append(f'Average stress change per exercise: {avg:+.1f} (negative = calmer).')
        by_activity = {}
        for c in rated:
            by_activity.setdefault(c.activity, []).append(c.stress_after - c.stress_before)
        lines.append('By activity:')
        for activity, diffs in sorted(by_activity.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
            lines.append(f'  - {activity.replace("-", " ").capitalize()}: '
                         f'{sum(diffs) / len(diffs):+.1f} on average ({len(diffs)}x)')
    lines.append('')
    lines.append('History (date, activity, before -> after):')
    for c in checkins[-50:]:
        before = '-' if c.stress_before is None else c.stress_before
        after = '-' if c.stress_after is None else c.stress_after
        lines.append(f'  {c.created_at:%Y-%m-%d %H:%M} UTC  {c.activity}: {before} -> {after}')
    doc = HealthDocument(patient_id=g.user.id, author_id=g.user.id,
                         author_name=f'{g.user.display_name} (Patient)',
                         title=f'Check-in progress report ({_now():%b %d, %Y})',
                         category='progress-report', body='\n'.join(lines))
    db.session.add(doc)
    db.session.commit()
    return jsonify(document=doc.to_dict()), 201


def _get_doc(doc_id):
    doc = db.session.get(HealthDocument, doc_id)
    if doc is None:
        abort(404, 'Not found.')
    require_access(doc.patient_id, 'documents')
    return doc


@bp.get('/api/documents/<int:doc_id>')
@roles_required('patient', 'provider')
def api_get_document(doc_id):
    return jsonify(document=_get_doc(doc_id).to_dict())


@bp.delete('/api/documents/<int:doc_id>')
@roles_required('patient', 'provider')
def api_delete_document(doc_id):
    doc = _get_doc(doc_id)
    # The patient can delete anything in their records; a provider only what they wrote.
    if g.user.id not in (doc.patient_id, doc.author_id):
        abort(403, 'You can only delete documents you wrote.')
    db.session.delete(doc)
    db.session.commit()
    return '', 204


# ---------- Alerts API (patient + linked family) ----------

@bp.get('/api/alerts')
@roles_required('patient', 'family')
def api_alerts():
    """Patient: their own alerts. Family: alerts for every patient who added them.
    Add ?unacknowledged=1 to get only new ones (handy for polling)."""
    if g.user.role == 'patient':
        patient_ids = [g.user.id]
    else:
        patient_ids = [l.patient_id for l in _links_for(g.user)]
    query = Alert.query.filter(Alert.patient_id.in_(patient_ids))
    if request.args.get('unacknowledged') in ('1', 'true'):
        query = query.filter(Alert.acknowledged_at.is_(None))
    alerts = query.order_by(Alert.created_at.desc()).limit(100).all()
    return jsonify(alerts=[a.to_dict() for a in alerts])


@bp.post('/api/alerts/sos')
@roles_required('patient')
def api_sos():
    """The patient's own 'I need support' button."""
    data = _json()
    kind = data.get('kind') or 'other'
    if kind not in ALERT_KINDS:
        abort(400, 'Unknown alert type.')
    alert = create_alert(g.user, kind, 'sos', (data.get('note') or '').strip())
    family = CareLink.query.join(User, CareLink.member_id == User.id).filter(
        CareLink.patient_id == g.user.id, User.role == 'family').count()
    return jsonify(alert=alert.to_dict(), family_notified=family), 201


@bp.post('/api/alerts/<int:alert_id>/acknowledge')
@roles_required('patient', 'family')
def api_acknowledge(alert_id):
    alert = db.session.get(Alert, alert_id)
    if alert is None:
        abort(404, 'Not found.')
    require_access(alert.patient_id, 'alerts')
    if alert.acknowledged_at is None:
        alert.acknowledged_at = _now()
        alert.acknowledged_by = g.user.display_name
        db.session.commit()
    return jsonify(alert=alert.to_dict())
