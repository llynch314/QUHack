"""Login tokens, route decorators and the access rules for each role.

Every route that touches a patient's data calls `require_access(patient_id, resource)`.
The rules live in one table (ACCESS) so they are easy to read and change.
"""
from functools import wraps

from flask import abort, current_app, g, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from models import CareLink, User, db

# What each role may see. Patients see only their own data; providers and
# family see a patient only if that patient has added them to their care team.
ACCESS = {
    "patient": {"documents", "alerts", "chat", "emotion", "care_team"},
    "provider": {"documents"},
    "family": {"alerts"},
}


# ---------- tokens ----------

def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="mind-connect-auth")


def issue_token(user):
    return _serializer().dumps({"uid": user.id})


def _user_from_request():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        data = _serializer().loads(header[7:], max_age=current_app.config["TOKEN_MAX_AGE"])
    except (BadSignature, SignatureExpired):
        return None
    return db.session.get(User, data.get("uid"))


# ---------- decorators ----------

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = _user_from_request()
        if user is None:
            abort(401, "Please log in.")
        g.user = user
        return fn(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if g.user.role not in roles:
                abort(403, f"This action is only for: {', '.join(roles)}.")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------- access checks ----------

def is_linked(patient_id, member_id):
    return db.session.query(CareLink.id).filter_by(
        patient_id=patient_id, member_id=member_id).first() is not None


def can_access(user, patient_id, resource):
    if resource not in ACCESS.get(user.role, set()):
        return False
    if user.role == "patient":
        return user.id == patient_id
    return is_linked(patient_id, user.id)


def require_access(patient_id, resource):
    if not can_access(g.user, patient_id, resource):
        abort(403, "You don't have access to this.")
