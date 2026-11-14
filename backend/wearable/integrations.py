"""The ONLY file in the wearable package that touches the team's auth / alerts / documents (PRD §0A).

Uses main's roles (User.role), care team (CareLink), urgent alerts (Alert) and health documents
(HealthDocument), so the watch shows up in the same places as everything else:

  - family see wearable alerts on their normal Alerts page (/family) and can acknowledge them there
  - patients see them on their Care Team page next to SOS / chat alerts
  - providers see wearable reports as health documents on My Patients -> patient (/provider/patients/<id>)
  - who can see what comes from auth.can_access (ACCESS table in auth.py)

WearableAlert keeps the wearable-only part of an alert: the "I'm OK" countdown (pending / cancelled).
When the countdown ends (or right away for cardiac warnings) a real Alert row is created.
"""
import logging
from datetime import datetime, timedelta, timezone

from flask import g

from auth import can_access
from models import ALERT_LABELS, Alert, CareLink, CheckIn, HealthDocument, ROLE_LABELS, User, _now, db

from .models import WearableAlert
from .security import as_utc, utcnow

log = logging.getLogger('mindconnect.wearable')
ROLES = ('patient', 'family', 'provider')
REPORT_CATEGORY = 'wearable-report'
REPORT_AUTHOR = 'AttuneMIND watch (automatic report)'
DEMO_PATIENT_SUB = 'dev-demo-patient'   # same demo accounts as main's /login/dev

# Labels for the family Alerts page (main's Alert.to_dict looks these up by kind).
ALERT_LABELS.setdefault('fall', 'Possible fall (watch)')
ALERT_LABELS.setdefault('cardiac_warning', 'Warning signs (watch)')
ALERT_LABELS.setdefault('distress', 'Very stressed (watch)')


def get_current_user():
    return g.get('user')


def get_role(user):
    if user is None:
        return 'anonymous'
    return user.role or 'patient'


def get_current_patient():
    user = get_current_user()
    return user if get_role(user) == 'patient' else None


def linked_patient_ids(user, role):
    if user is None or get_role(user) != role:
        return []
    return [l.patient_id for l in CareLink.query.filter_by(member_id=user.id)]


def can_view_vitals(user, patient_id):
    """Minimum necessary: only the patient sees their own vitals. Family get alerts only,
    providers get reports only (PRD §4). Enforced on the server."""
    return user is not None and get_role(user) == 'patient' and user.id == patient_id


def can_view_reports(user, patient_id):
    return can_access(user, patient_id, 'documents')


def can_view_alerts(user, patient_id):
    return can_access(user, patient_id, 'alerts')


def family_count(patient_id):
    return CareLink.query.join(User, CareLink.member_id == User.id).filter(
        CareLink.patient_id == patient_id, User.role == 'family').count()


# ---------- alerts ----------

def notify_family(patient_id, kind, note, tier, delay_seconds=0, now=None):
    """Create a family alert. delay_seconds > 0 makes it 'pending' (fall countdown);
    escalation.promote_due_alerts() publishes it when the countdown ends."""
    now = now or utcnow()
    alert = WearableAlert(patient_id=patient_id, tier=tier, kind=kind, note=note, source='wearable',
                          status='pending' if delay_seconds else 'open',
                          send_at=now + timedelta(seconds=delay_seconds), created_at=now)
    db.session.add(alert)
    db.session.flush()
    if not delay_seconds:
        publish_alert(alert)
    db.session.commit()
    return alert


def publish_alert(walert):
    """Turn a wearable alert into a real family alert (main's Alert table). Caller commits."""
    if walert.alert_id:
        return
    main = Alert(patient_id=walert.patient_id, kind=walert.kind, source='wearable', note=walert.note[:500])
    db.session.add(main)
    db.session.flush()
    walert.alert_id = main.id
    walert.status = 'open'
    notify_family_phones(main)


def _team_notifier():
    """main's care.notify_family (push + text). Older main called it text_family."""
    import care
    return getattr(care, 'notify_family', None) or getattr(care, 'text_family')


def notify_family_phones(alert):
    """Same phone push / text message family get for SOS and chat alerts, if they set them up."""
    try:
        from flask import current_app, has_request_context

        notify = _team_notifier()
        if has_request_context():
            notify(alert)
        else:   # simulator CLI: url_for needs a request context
            with current_app.test_request_context():
                notify(alert)
    except Exception:
        log.warning('wearable: family phone notification failed (alert=%s)', alert.id)


def main_alert(walert):
    return db.session.get(Alert, walert.alert_id) if walert.alert_id else None


def acknowledge(walert, user):
    main = main_alert(walert)
    if main is not None and main.acknowledged_at is None:
        main.acknowledged_at = _now()
        main.acknowledged_by = user.display_name
    if walert.status == 'open':
        walert.status, walert.ack_at, walert.ack_by = 'acknowledged', utcnow(), user.id
    db.session.commit()


def sync_ack(walert):
    """Family acknowledge on the Alerts page -> mirror it on the wearable alert."""
    main = main_alert(walert)
    if walert.status == 'open' and main is not None and main.acknowledged_at is not None:
        walert.status, walert.ack_at = 'acknowledged', main.acknowledged_at
        return True
    return False


def delete_alerts(patient_id):
    return Alert.query.filter_by(patient_id=patient_id, source='wearable').delete(synchronize_session=False)


# ---------- provider reports (health documents) ----------

def save_provider_report(patient_id, title, body):
    doc = HealthDocument(patient_id=patient_id, author_id=None, author_name=REPORT_AUTHOR,
                         title=title[:200], category=REPORT_CATEGORY, body=body)
    db.session.add(doc)
    db.session.commit()
    return doc


def reports_for(patient_ids, limit=50):
    if not patient_ids:
        return []
    return (HealthDocument.query.filter(HealthDocument.patient_id.in_(patient_ids),
                                        HealthDocument.category == REPORT_CATEGORY)
            .order_by(HealthDocument.id.desc()).limit(limit).all())


def get_report(report_id):
    doc = db.session.get(HealthDocument, report_id)
    return doc if doc is not None and doc.category == REPORT_CATEGORY else None


def last_report(patient_id):
    return (HealthDocument.query.filter_by(patient_id=patient_id, category=REPORT_CATEGORY)
            .order_by(HealthDocument.id.desc()).first())


def delete_reports(patient_id):
    return HealthDocument.query.filter_by(patient_id=patient_id, category=REPORT_CATEGORY) \
        .delete(synchronize_session=False)


def get_checkins(patient_id):
    """Main's before/after stress check-ins (used by the report and the resolution plan)."""
    return CheckIn.query.filter_by(user_id=patient_id).order_by(CheckIn.created_at).all()


# ---------- DEV_LOGIN demo accounts ----------

def demo_user(role):
    """The same demo accounts main's /login/dev uses, ready to go: consent done, provider profile
    filled in, and family + provider already on the demo patient's care team."""
    sub = f'dev-demo-{role}'
    user = User.query.filter_by(google_sub=sub).first()
    if user is None:
        user = User(google_sub=sub, name=f'Demo {ROLE_LABELS[role]}', email=f'demo-{role}@example.com')
        db.session.add(user)
    user.role = role   # fixes demo accounts created before roles existed
    if user.terms_accepted_at is None:
        user.terms_accepted_at = datetime.now(timezone.utc)
    if role == 'provider' and not user.organization:
        user.organization, user.specialty = 'Demo Clinic', 'Therapist'
    db.session.commit()
    if role != 'patient':
        patient = demo_user('patient')
        if not CareLink.query.filter_by(patient_id=patient.id, member_id=user.id).first():
            db.session.add(CareLink(patient_id=patient.id, member_id=user.id))
            db.session.commit()
    return user


def link_demo_team():
    """DEV_LOGIN: put whichever demo family member / provider exist on the demo patient's care team,
    without touching their consent or profile (used after the normal Sign in -> demo buttons)."""
    patient = demo_patient()
    if patient is None:
        return 0
    added = 0
    for role in ('family', 'provider'):
        member = User.query.filter_by(google_sub=f'dev-demo-{role}', role=role).first()
        if member and not CareLink.query.filter_by(patient_id=patient.id, member_id=member.id).first():
            db.session.add(CareLink(patient_id=patient.id, member_id=member.id))
            added += 1
    if added:
        db.session.commit()
    return added


def demo_patient():
    return User.query.filter_by(google_sub=DEMO_PATIENT_SUB).first()
