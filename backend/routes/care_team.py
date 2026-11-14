"""Care team: patients add/remove the providers and family members who can see their data."""
from flask import Blueprint, abort, g, jsonify, request

from auth import login_required, roles_required
from models import CareLink, User, db

bp = Blueprint("care_team", __name__, url_prefix="/api/care-team")


@bp.get("")
@login_required
def list_links():
    """Patients see their care team; providers/family see the patients they're linked to."""
    if g.user.role == "patient":
        links = CareLink.query.filter_by(patient_id=g.user.id).all()
    else:
        links = CareLink.query.filter_by(member_id=g.user.id).all()
    return jsonify(links=[l.to_dict() for l in links])


@bp.post("")
@roles_required("patient")
def add_member():
    email = ((request.get_json(silent=True) or {}).get("email") or "").strip().lower()
    member = User.query.filter_by(email=email).first()
    if member is None:
        abort(404, "No account with that email. Ask them to sign up first.")
    if member.role not in ("provider", "family"):
        abort(400, "You can only add health providers and family members.")
    if CareLink.query.filter_by(patient_id=g.user.id, member_id=member.id).first():
        abort(409, "They're already on your care team.")
    link = CareLink(patient_id=g.user.id, member_id=member.id)
    db.session.add(link)
    db.session.commit()
    return jsonify(link=link.to_dict()), 201


@bp.delete("/<int:link_id>")
@roles_required("patient")
def remove_member(link_id):
    link = db.session.get(CareLink, link_id)
    if link is None or link.patient_id != g.user.id:
        abort(404, "Not found.")
    db.session.delete(link)
    db.session.commit()
    return "", 204
