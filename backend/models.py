"""Database models (SQLite by default; set DATABASE_URL in .env for Postgres etc.).

Privacy by design: we store only what the features need. Chat messages are NOT
stored. Check-in ratings are stored for signed-in users; expression readings only if
the user opted in on the consent screen. Everything is deleted with the account.
"""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


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
    created_at = db.Column(db.DateTime(timezone=True), default=_now)
    # Consent, collected on the consent screen when the account is created.
    terms_accepted_at = db.Column(db.DateTime(timezone=True))   # None = hasn't agreed yet
    save_expressions = db.Column(db.Boolean, nullable=False, default=False)  # opt-in only
    expressions_consent_at = db.Column(db.DateTime(timezone=True))
    checkins = db.relationship('CheckIn', backref='user', cascade='all, delete-orphan',
                               order_by='CheckIn.created_at')
    expressions = db.relationship('ExpressionReading', backref='user', cascade='all, delete-orphan',
                                  order_by='ExpressionReading.created_at')


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
    }
    with db.engine.begin() as conn:
        for name, ddl in new_columns.items():
            if name not in existing:
                conn.execute(db.text(f'ALTER TABLE "user" ADD COLUMN {name} {ddl}'))
