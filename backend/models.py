"""Database models for Mind Connect.

Three kinds of account share one `User` table, told apart by `role`:
  - patient  : the person using the app; owns all of their own data
  - provider : a health provider; sees only the patient's health documents
  - family   : a family member; sees only urgent alerts (panic attack, meltdown, crisis)

A provider or family member only sees a patient after that patient adds them
to their care team (a `CareLink`). The patient can remove them at any time.
"""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

ROLES = ("patient", "provider", "family")
ALERT_KINDS = ("panic_attack", "meltdown", "crisis", "other")


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat() if dt else None


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # Patients only: when the chatbot detects a panic attack, meltdown or crisis,
    # automatically alert their family members. Patients can switch this off.
    auto_alerts = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        data = {"id": self.id, "email": self.email, "name": self.name, "role": self.role}
        if self.role == "patient":
            data["auto_alerts"] = self.auto_alerts
        return data


class CareLink(db.Model):
    """A patient granting a provider or family member access."""
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    member_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    patient = db.relationship("User", foreign_keys=[patient_id])
    member = db.relationship("User", foreign_keys=[member_id])

    __table_args__ = (db.UniqueConstraint("patient_id", "member_id"),)

    def to_dict(self):
        return {
            "id": self.id,
            "patient": {"id": self.patient.id, "name": self.patient.name},
            "member": {"id": self.member.id, "name": self.member.name,
                       "email": self.member.email, "role": self.member.role},
            "created_at": iso(self.created_at),
        }


class HealthDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False, default="note")
    body = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    author = db.relationship("User", foreign_keys=[author_id])

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "author": {"id": self.author.id, "name": self.author.name, "role": self.author.role},
            "title": self.title,
            "category": self.category,
            "body": self.body,
            "created_at": iso(self.created_at),
        }


class Alert(db.Model):
    """An urgent event (panic attack, meltdown, crisis). The only thing family can see."""
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    kind = db.Column(db.String(30), nullable=False)
    source = db.Column(db.String(20), nullable=False)  # "manual" (SOS button) or "chat"
    note = db.Column(db.String(500), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    acknowledged_at = db.Column(db.DateTime(timezone=True))
    acknowledged_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    patient = db.relationship("User", foreign_keys=[patient_id])
    acknowledged_by = db.relationship("User", foreign_keys=[acknowledged_by_id])

    def to_dict(self):
        return {
            "id": self.id,
            "patient": {"id": self.patient.id, "name": self.patient.name},
            "kind": self.kind,
            "source": self.source,
            "note": self.note,
            "created_at": iso(self.created_at),
            "acknowledged_at": iso(self.acknowledged_at),
            "acknowledged_by": self.acknowledged_by.name if self.acknowledged_by else None,
        }


class ChatMessage(db.Model):
    """Patient <-> chatbot conversation. Private to the patient."""
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    sender = db.Column(db.String(10), nullable=False)  # "user" or "model"
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    def to_dict(self):
        return {"id": self.id, "sender": self.sender, "text": self.text,
                "created_at": iso(self.created_at)}
