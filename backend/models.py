"""Database models (SQLite by default; set DATABASE_URL in .env for Postgres etc.).

Privacy by design: we store only what the features need. Chat messages are NOT
stored; only check-in ratings, which the user can export or delete at any time.
"""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _now():
    return datetime.now(timezone.utc)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_sub = db.Column(db.String(64), unique=True, index=True)  # Google account ID
    email = db.Column(db.String(255))
    name = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), default=_now)
    checkins = db.relationship('CheckIn', backref='user', cascade='all, delete-orphan',
                               order_by='CheckIn.created_at')


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
            'created_at': self.created_at.isoformat(),
            'activity': self.activity,
            'stress_before': self.stress_before,
            'stress_after': self.stress_after,
            'note': self.note,
        }
