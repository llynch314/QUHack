"""Wearable tables (PRD §6.4). All prefixed `wearable_`; no edits to backend/models.py.

Columns ending in _enc are encrypted at rest with Fernet (see security.EncryptedText).
patient_id is the existing User.id.
"""
from models import db

from .security import EncryptedText, as_utc, utcnow

CONSENT_VERSION = '2026-11-v1'


def _iso(dt):
    """SQLite returns naive datetimes; always send explicit UTC so browsers don't read them as local time."""
    return as_utc(dt).isoformat() if dt else None


class WearableProfile(db.Model):
    __tablename__ = 'wearable_profile'
    patient_id = db.Column(db.Integer, primary_key=True)
    baseline_resting_hr = db.Column(db.Float, default=65, nullable=False)
    baseline_hrv = db.Column(db.Float, default=45, nullable=False)
    family_tier2_alerts = db.Column(db.Boolean, default=False, nullable=False)
    emergency_alerts = db.Column(db.Boolean, default=True, nullable=False)
    ai_explanations = db.Column(db.Boolean, default=True, nullable=False)
    consent_version = db.Column(db.String(32))
    consent_at = db.Column(db.DateTime(timezone=True))

    def to_dict(self):
        return {
            'baseline_resting_hr': self.baseline_resting_hr,
            'baseline_hrv': self.baseline_hrv,
            'family_tier2_alerts': self.family_tier2_alerts,
            'emergency_alerts': self.emergency_alerts,
            'ai_explanations': self.ai_explanations,
            'consent_version': self.consent_version,
            'consent_current': self.consent_version == CONSENT_VERSION,
            'consent_at': _iso(self.consent_at),
        }


class WearableDevice(db.Model):
    __tablename__ = 'wearable_device'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    label = db.Column(db.String(80), nullable=False)
    source = db.Column(db.String(32), nullable=False, default='apple_watch')
    last_seen_at = db.Column(db.DateTime(timezone=True))
    revoked_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'label': self.label, 'source': self.source,
            'last_seen_at': _iso(self.last_seen_at),
            'revoked': self.revoked_at is not None,
            'created_at': _iso(self.created_at),
        }


class VitalSample(db.Model):
    __tablename__ = 'wearable_vital_sample'
    __table_args__ = (db.UniqueConstraint('patient_id', 'type', 'ts', name='uq_wearable_sample'),)
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, nullable=False, index=True)
    type = db.Column(db.String(32), nullable=False)
    value_enc = db.Column(EncryptedText, nullable=False)
    ts = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    source = db.Column(db.String(32), nullable=False)


class WearableEvent(db.Model):
    """Falls, self-reports and patient corrections ("exercising", "not_okay", "im_ok")."""
    __tablename__ = 'wearable_event'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, nullable=False, index=True)
    type = db.Column(db.String(32), nullable=False)
    ts = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    meta_enc = db.Column(EncryptedText)
    source = db.Column(db.String(32), nullable=False, default='patient')


class StateReading(db.Model):
    __tablename__ = 'wearable_state_reading'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, nullable=False, index=True)
    state = db.Column(db.String(20), nullable=False)
    kind = db.Column(db.String(32))           # fall / cardiac_warning for emergencies
    confidence = db.Column(db.Float, nullable=False)
    reasons_enc = db.Column(EncryptedText)    # {"reasons": [...], "explanation": "...", "metrics": {...}}
    ts = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)


class WearableNudge(db.Model):
    """Message to the patient (shown in the app and pushed to phone/watch). No vitals in text."""
    __tablename__ = 'wearable_nudge'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, nullable=False, index=True)
    tier = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(32), nullable=False)
    message = db.Column(db.String(300), nullable=False)
    link = db.Column(db.String(120))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)
    seen_at = db.Column(db.DateTime(timezone=True))

    def to_dict(self):
        return {'id': self.id, 'tier': self.tier, 'kind': self.kind, 'message': self.message,
                'link': self.link, 'created_at': _iso(self.created_at),
                'seen': self.seen_at is not None}


class WearableAlert(db.Model):
    """Standalone fallback for the team's Alert model (replaced after the roles merge).
    status: pending (Tier 3 fall countdown) -> open -> acknowledged, or cancelled ("I'm OK")."""
    __tablename__ = 'wearable_alert'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, nullable=False, index=True)
    tier = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(32), nullable=False)
    note = db.Column(db.String(300), nullable=False)
    source = db.Column(db.String(32), nullable=False, default='wearable')
    status = db.Column(db.String(16), nullable=False, default='open')
    send_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)
    ack_at = db.Column(db.DateTime(timezone=True))
    ack_by = db.Column(db.Integer)

    def to_dict(self):
        return {'id': self.id, 'patient_id': self.patient_id, 'tier': self.tier, 'kind': self.kind,
                'note': self.note, 'source': self.source, 'status': self.status,
                'send_at': _iso(self.send_at), 'created_at': _iso(self.created_at),
                'ack_at': _iso(self.ack_at), 'ack_by': self.ack_by}


class WearableReport(db.Model):
    """Standalone fallback for HealthDocument(category="wearable_report")."""
    __tablename__ = 'wearable_report'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    body_enc = db.Column(EncryptedText, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)


class WearableCareLink(db.Model):
    """Standalone stand-in for the team's CareLink, so family/provider access can be
    demoed and tested on this branch. Replaced by CareLink after the roles merge."""
    __tablename__ = 'wearable_care_link'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, nullable=False, index=True)
    member_user_id = db.Column(db.Integer, nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False)   # family | provider
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)


class AuditLog(db.Model):
    """Append-only: there is no update or delete route for this table."""
    __tablename__ = 'wearable_audit_log'
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer)
    actor_role = db.Column(db.String(16))
    action = db.Column(db.String(48), nullable=False)
    resource = db.Column(db.String(80))
    patient_id = db.Column(db.Integer, index=True)
    ip = db.Column(db.String(64))
    ts = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)
    outcome = db.Column(db.String(16), nullable=False)

    def to_dict(self):
        return {'id': self.id, 'actor_id': self.actor_id, 'actor_role': self.actor_role,
                'action': self.action, 'resource': self.resource, 'patient_id': self.patient_id,
                'ts': _iso(self.ts), 'outcome': self.outcome}


class AIUsageLog(db.Model):
    """Metadata only, never content (PRD §5A.4)."""
    __tablename__ = 'wearable_ai_usage_log'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, index=True)
    feature = db.Column(db.String(48), nullable=False)
    model = db.Column(db.String(64), nullable=False)
    tier = db.Column(db.String(16), nullable=False)
    fields_sent = db.Column(db.String(200), nullable=False)
    ts = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)
