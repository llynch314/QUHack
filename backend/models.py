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

from organizations import organization_for_email

db = SQLAlchemy()

ROLES = ('patient', 'provider', 'family')
ROLE_LABELS = {'patient': 'Patient', 'provider': 'Health provider', 'family': 'Family member'}
# Dashboard mood colors (frontend/test.html). Name -> hex, in the order the picker shows them.
MOOD_COLORS = {'Yellow': '#E8C24A', 'Green': '#8FB08A', 'Blue': '#7F9FC4', 'Red': '#D4705F', 'Purple': '#A58BC0'}
MOOD_MEANINGS = {
    'Yellow': 'Happy and full of energy',
    'Green': 'Calm and steady',
    'Blue': 'Quiet or a little sad',
    'Red': 'Strong feelings, like anger or worry',
    'Purple': 'Dreamy and thoughtful',
}
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
    email_verified = db.Column(db.Boolean, nullable=False, default=False)  # as reported by Google
    name = db.Column(db.String(255))
    role = db.Column(db.String(20), nullable=False, default='patient', server_default='patient')
    # Patients only: alert family automatically when chat shows signs of a panic attack,
    # meltdown or crisis. Patients can switch this off on their Care Team page.
    auto_alerts = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    # Providers only: shown to patients so they know who they're sharing records with.
    # Self-reported, unless the email domain is on the verified list (see organizations.py).
    organization = db.Column(db.String(200))    # hospital, clinic or practice
    specialty = db.Column(db.String(120))       # e.g. "Psychiatrist", "Therapist (LCSW)"
    license_number = db.Column(db.String(60))   # optional, e.g. state licence or NPI
    # Family only: text alerts to this number. Set only after it is confirmed with a code.
    phone = db.Column(db.String(20))            # E.164, e.g. +15551234567
    sms_alerts = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    # Family only: ntfy topic for phone push notifications (see push.py). None = off.
    ntfy_topic = db.Column(db.String(64))
    created_at = db.Column(db.DateTime(timezone=True), default=_now)
    # Consent, collected on the consent screen when the account is created.
    terms_accepted_at = db.Column(db.DateTime(timezone=True))   # None = hasn't agreed yet
    save_expressions = db.Column(db.Boolean, nullable=False, default=False)  # opt-in only
    expressions_consent_at = db.Column(db.DateTime(timezone=True))
    checkins = db.relationship('CheckIn', backref='user', cascade='all, delete-orphan',
                               order_by='CheckIn.created_at')
    expressions = db.relationship('ExpressionReading', backref='user', cascade='all, delete-orphan',
                                  order_by='ExpressionReading.created_at')
    moods = db.relationship('MoodEntry', backref='user', cascade='all, delete-orphan',
                            order_by='MoodEntry.created_at')

    @property
    def display_name(self):
        return self.name or self.email or f'User {self.id}'

    @property
    def phone_masked(self):
        """e.g. '(***) ***-4567', so the full number isn't shown on screen."""
        return f'(***) ***-{self.phone[-4:]}' if self.phone else None

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def needs_profile(self):
        """Providers must say where they work before using the provider pages."""
        return self.role == 'provider' and not self.organization

    @property
    def verified_organization(self):
        """The organisation a provider's verified email domain belongs to, or None."""
        if self.role != 'provider' or not self.email_verified:
            return None
        return organization_for_email(self.email)

    @property
    def is_verified_provider(self):
        org = self.verified_organization
        return org is not None and org == self.organization

    @property
    def provider_summary(self):
        """e.g. 'Psychiatrist, City Hospital'; '' for non-providers or empty profiles."""
        if self.role != 'provider':
            return ''
        return ', '.join(p for p in (self.specialty, self.organization) if p)


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


class MoodEntry(db.Model):
    """A mood color the patient picked on the dashboard. Picks a few seconds apart replace each
    other (see MOOD_MERGE_WINDOW in app.py), so trying out colors doesn't fill the history."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    color = db.Column(db.String(10), nullable=False)    # a key of MOOD_COLORS
    created_at = db.Column(db.DateTime(timezone=True), default=_now, index=True)

    def to_dict(self):
        return {'id': self.id, 'color': self.color, 'hex': MOOD_COLORS.get(self.color),
                'meaning': MOOD_MEANINGS.get(self.color),
                'created_at': as_utc(self.created_at).isoformat()}


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
                       'email': self.member.email, 'role': self.member.role,
                       'organization': self.member.organization,
                       'specialty': self.member.specialty,
                       'verified': self.member.is_verified_provider},
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


class PhoneVerification(db.Model):
    """A pending 6-digit code sent to confirm a phone number. One per user; deleted once used."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    phone = db.Column(db.String(20), nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)   # never the code itself
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=_now)


def delete_user_everywhere(user):
    """Delete a user and everything tied to them (check-ins, care links, documents, alerts)."""
    CareLink.query.filter((CareLink.patient_id == user.id) | (CareLink.member_id == user.id)).delete()
    HealthDocument.query.filter_by(patient_id=user.id).delete()
    HealthDocument.query.filter_by(author_id=user.id).update({'author_id': None})
    Alert.query.filter_by(patient_id=user.id).delete()
    PhoneVerification.query.filter_by(user_id=user.id).delete()
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
        'email_verified': 'BOOLEAN NOT NULL DEFAULT FALSE',
        'organization': 'VARCHAR(200)',
        'specialty': 'VARCHAR(120)',
        'license_number': 'VARCHAR(60)',
        'phone': 'VARCHAR(20)',
        'sms_alerts': 'BOOLEAN NOT NULL DEFAULT TRUE',
        'ntfy_topic': 'VARCHAR(64)',
    }
    with db.engine.begin() as conn:
        for name, ddl in new_columns.items():
            if name not in existing:
                conn.execute(db.text(f'ALTER TABLE "user" ADD COLUMN {name} {ddl}'))
