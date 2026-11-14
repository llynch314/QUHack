"""The ONLY file in the wearable package that touches teammates' auth / alerts / documents (PRD §0A).

STANDALONE (now, on feature/wearable):
  - users come from main's Google / DEV_LOGIN sign-in (models.User)
  - family / provider roles come from WearableCareLink (wearable-owned)
  - alerts go to WearableAlert, reports go to WearableReport

AFTER THE ROLES MERGE, change only this file:
  - get_role(user)            -> return user.role
  - can_view_vitals(...)      -> add "vitals" to ACCESS["patient"] and call require_access(user, "vitals", patient_id)
  - notify_family(...)        -> create_alert(patient_id, kind=kind, note=note, source="wearable")
  - save_provider_report(...) -> HealthDocument(patient_id=..., category="wearable_report", author=patient, body=...)
  - linked_patient_ids(...)   -> query CareLink
"""
from datetime import timedelta

from flask import g

from models import CheckIn, User, db

from .models import WearableAlert, WearableCareLink, WearableReport
from .security import utcnow

ROLES = ('patient', 'family', 'provider')


def get_current_user():
    return g.get('user')


def get_role(user):
    if user is None:
        return 'anonymous'
    link = WearableCareLink.query.filter_by(member_user_id=user.id).first()
    return link.role if link else 'patient'


def get_current_patient():
    """The signed-in user, if they are a patient. None for family/provider/anonymous."""
    user = get_current_user()
    return user if user is not None and get_role(user) == 'patient' else None


def linked_patient_ids(user, role):
    return [l.patient_id for l in WearableCareLink.query.filter_by(member_user_id=user.id, role=role)]


def can_view_vitals(user, patient_id):
    """Minimum necessary: only the patient sees their own vitals. Family get alerts only,
    providers get reports only (PRD §4). Enforced on the server."""
    return user is not None and get_role(user) == 'patient' and user.id == patient_id


def can_view_reports(user, patient_id):
    if user is None:
        return False
    role = get_role(user)
    if role == 'patient':
        return user.id == patient_id
    return role == 'provider' and patient_id in linked_patient_ids(user, 'provider')


def can_view_alerts(user, patient_id):
    if user is None:
        return False
    role = get_role(user)
    if role == 'patient':
        return user.id == patient_id
    return role == 'family' and patient_id in linked_patient_ids(user, 'family')


def notify_family(patient_id, kind, note, tier, delay_seconds=0, now=None):
    """Create a family alert. delay_seconds > 0 makes it 'pending' (fall countdown);
    escalation.promote_due_alerts() opens it when the countdown expires."""
    now = now or utcnow()
    alert = WearableAlert(patient_id=patient_id, tier=tier, kind=kind, note=note, source='wearable',
                          status='pending' if delay_seconds else 'open',
                          send_at=now + timedelta(seconds=delay_seconds), created_at=now)
    db.session.add(alert)
    db.session.commit()
    return alert


def save_provider_report(patient_id, title, body):
    report = WearableReport(patient_id=patient_id, title=title, body_enc=body)
    db.session.add(report)
    db.session.commit()
    return report


def get_checkins(patient_id):
    """Main's before/after stress check-ins (used by the report and the resolution plan)."""
    return CheckIn.query.filter_by(user_id=patient_id).order_by(CheckIn.created_at).all()


def get_or_create_demo_member(role, patient):
    """DEV_LOGIN only: a demo family member / provider linked to the demo patient."""
    sub = f'dev-demo-{role}'
    user = User.query.filter_by(google_sub=sub).first()
    if user is None:
        user = User(google_sub=sub, name=f'Demo {role.capitalize()}', email=f'{role}@example.com')
        db.session.add(user)
        db.session.commit()
    if not WearableCareLink.query.filter_by(member_user_id=user.id, patient_id=patient.id).first():
        db.session.add(WearableCareLink(patient_id=patient.id, member_user_id=user.id, role=role))
        db.session.commit()
    return user
