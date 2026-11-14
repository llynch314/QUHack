"""Database models (SQLite by default; set DATABASE_URL in .env for Postgres etc.).

Privacy by design: we store only what the features need. Chat messages are NOT
stored. Check-in ratings are stored for signed-in users; expression readings only if
the user opted in on the consent screen. Everything is deleted with the account.

Three kinds of account share the User table, told apart by `role`:
  - patient  : the person using the app; full access to their own data
  - provider : a health provider; sees only the health documents of patients who added them
  - family   : a family member; sees only urgent alerts (panic attack, meltdown, crisis)
               for patients who added them
"""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

ROLES = ('patient', 'provider', 'family')
ROLE_LABELS = {'patient': 'Patient', 'provider': 'Health provider', 'family': 'Family member'}
ALERT_KINDS = ('panic_attack', 'meltdown', 'crisis', 'other')
ALERT_LABELS = {'panic_attack': 'Panic attack', 'meltdown': 'Meltdown',
                'crisis': 'Crisis', 'other': 'Needs support'}


def _now():
    return datetime.now(timezone.utc)


def as_utc(dt):
    """SQLite returns datetimes without a time zone; they are stored in UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_sub = db.Column(db.String(64), unique=True, index=True)  # Google account ID
    email = db.Column(db.String(255))
    name = db.Column(db.String(255))
    role = db.Column(db.String(20), nullable=False, default='patient', server_default='patient')
    # Patients only: alert family automatically when chat shows signs of a panic attack,
    # meltdown or crisis. Patients can switch this off on their Care Team page.
    auto_alerts = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    created_at = db.Column(db.DateTime(timezone=True), default=_now)
    # Consent, collected on the consent screen when the account is created.
    terms_accepted_at = db.Column(db.DateTime(timezone=True))   # None = hasn't agreed yet
    save_expressions = db.Column(db.Boolean, nullable=False, default=False)  # opt-in only
    expressions_consent_at = db.Column(db.DateTime(timezone=True))
    checkins = db.relationship('CheckIn', backref='user', cascade='all, delete-orphan',
                               order_by='CheckIn.created_at')
    expressions = db.relationship('ExpressionReading', backref='user', cascade='all, delete-orphan',
                                  order_by='ExpressionReading.created_at')

    @property
    def display_name(self):
        return self.name or self.email or f'User {self.id}'

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)


class CheckIn(db.Model):
    """A stress rating before and/or after an activity (breathing, grounding, chat, ...)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_now)
    activity = db.Column(db.String(40), nullable=False)
    stress_before = db.Column(db.Integer)   # 0 (calm) to 10 (most stressed)
    stress_after = db.Column(db.Integer)
    note = db.Column(db.String(500))        # optional, written by the user

    def to_dict(self):
        return {
            'id': self.id,
            'created_at': as_utc(self.created_at).isoformat(),
            'activity': self.activity,
            'stress_before': self.stress_before,
            'stress_after': self.stress_after,
            'note': self.note,
        }


class ExpressionReading(db.Model):
    """One facial expression reading from the camera (only saved if the user opted in)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_now, index=True)
    emotion = db.Column(db.String(20), nullable=False)    # happy, sad, angry, fear, surprise, disgust, neutral
    source = db.Column(db.String(10), nullable=False)     # 'chat' or 'voice'

    def to_dict(self):
        return {'id': self.id, 'created_at': as_utc(self.created_at).isoformat(),
                'emotion': self.emotion, 'source': self.source}


class CareLink(db.Model):
    """A patient granting a provider or family member access. The patient can remove it any time."""
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    member_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_now)

    patient = db.relationship('User', foreign_keys=[patient_id])
    member = db.relationship('User', foreign_keys=[member_id])

    __table_args__ = (db.UniqueConstraint('patient_id', 'member_id'),)

    def to_dict(self):
        return {
            'id': self.id,
            'patient': {'id': self.patient.id, 'name': self.patient.display_name},
            'member': {'id': self.member.id, 'name': self.member.display_name,
                       'email': self.member.email, 'role': self.member.role},
            'created_at': as_utc(self.created_at).isoformat(),
        }


class HealthDocument(db.Model):
    """A health record for a patient. Visible to the patient and their linked providers only."""
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    author_name = db.Column(db.String(255))   # kept in case the author deletes their account
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False, default='note')
    body = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(db.DateTime(timezone=True), default=_now)

    def to_dict(self):
        return {
            'id': self.id,
            'patient_id': self.patient_id,
            'author_id': self.author_id,
            'author_name': self.author_name,
            'title': self.title,
            'category': self.category,
            'body': self.body,
            'created_at': as_utc(self.created_at).isoformat(),
        }


class Alert(db.Model):
    """An urgent event (panic attack, meltdown, crisis). The only thing family members see.

    Never contains chat text: the note is either generic or written by the patient (SOS button).
    """
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    kind = db.Column(db.String(30), nullable=False)
    source = db.Column(db.String(20), nullable=False)   # 'sos' (patient pressed a button) or 'chat'
    note = db.Column(db.String(500), nullable=False, default='')
    created_at = db.Column(db.DateTime(timezone=True), default=_now)
    acknowledged_at = db.Column(db.DateTime(timezone=True))
    acknowledged_by = db.Column(db.String(255))

    patient = db.relationship('User', foreign_keys=[patient_id])

    def to_dict(self):
        return {
            'id': self.id,
            'patient': {'id': self.patient.id, 'name': self.patient.display_name},
            'kind': self.kind,
            'label': ALERT_LABELS.get(self.kind, self.kind),
            'source': self.source,
            'note': self.note,
            'created_at': as_utc(self.created_at).isoformat(),
            'acknowledged_at': as_utc(self.acknowledged_at).isoformat() if self.acknowledged_at else None,
            'acknowledged_by': self.acknowledged_by,
        }


def delete_user_everywhere(user):
    """Delete a user and everything tied to them (check-ins, care links, documents, alerts)."""
    CareLink.query.filter((CareLink.patient_id == user.id) | (CareLink.member_id == user.id)).delete()
    HealthDocument.query.filter_by(patient_id=user.id).delete()
    HealthDocument.query.filter_by(author_id=user.id).update({'author_id': None})
    Alert.query.filter_by(patient_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()


def add_missing_columns():
    """create_all() doesn't add new columns to existing tables; add the ones we added since."""
    inspector = db.inspect(db.engine)
    if 'user' not in inspector.get_table_names():
        return
    existing = {c['name'] for c in inspector.get_columns('user')}
    new_columns = {
        'terms_accepted_at': 'TIMESTAMP',
        'save_expressions': 'BOOLEAN NOT NULL DEFAULT FALSE',
        'expressions_consent_at': 'TIMESTAMP',
        'role': "VARCHAR(20) NOT NULL DEFAULT 'patient'",
        'auto_alerts': 'BOOLEAN NOT NULL DEFAULT TRUE',
    }
    with db.engine.begin() as conn:
        for name, ddl in new_columns.items():
            if name not in existing:
                conn.execute(db.text(f'ALTER TABLE "user" ADD COLUMN {name} {ddl}'))
