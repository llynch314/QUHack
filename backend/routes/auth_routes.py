"""Register, log in, and view/update your own account."""
import re

from flask import Blueprint, abort, g, jsonify, request

from auth import issue_token, login_required
from models import ROLES, User, db

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _json():
    return request.get_json(silent=True) or {}


@bp.post("/register")
def register():
    data = _json()
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    password = data.get("password") or ""
    role = data.get("role")

    if role not in ROLES:
        abort(400, f"role must be one of: {', '.join(ROLES)}")
    if not EMAIL_RE.match(email):
        abort(400, "A valid email is required.")
    if not name:
        abort(400, "Name is required.")
    if len(password) < 8:
        abort(400, "Password must be at least 8 characters.")
    if User.query.filter_by(email=email).first():
        abort(409, "An account with that email already exists.")

    user = User(email=email, name=name, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify(token=issue_token(user), user=user.to_dict()), 201


@bp.post("/login")
def login():
    data = _json()
    email = (data.get("email") or "").strip().lower()
    user = User.query.filter_by(email=email).first()
    if user is None or not user.check_password(data.get("password") or ""):
        abort(401, "Incorrect email or password.")
    # Optional: the frontend can send which login page was used, so a family
    # member can't sign in on the patient page by mistake.
    expected = data.get("role")
    if expected and expected != user.role:
        abort(403, f"This account is a {user.role} account. Please use the {user.role} login.")
    return jsonify(token=issue_token(user), user=user.to_dict())


@bp.get("/me")
@login_required
def me():
    return jsonify(user=g.user.to_dict())


@bp.patch("/me")
@login_required
def update_me():
    data = _json()
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            abort(400, "Name can't be empty.")
        g.user.name = name
    if "auto_alerts" in data:
        if g.user.role != "patient":
            abort(400, "Only patients have alert settings.")
        g.user.auto_alerts = bool(data["auto_alerts"])
    db.session.commit()
    return jsonify(user=g.user.to_dict())
