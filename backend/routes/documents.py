"""Health documents. Visible to the patient and their linked health providers only."""
from flask import Blueprint, abort, g, jsonify, request

from auth import login_required, require_access
from models import HealthDocument, db

bp = Blueprint("documents", __name__, url_prefix="/api")


@bp.get("/patients/<int:patient_id>/documents")
@login_required
def list_documents(patient_id):
    require_access(patient_id, "documents")
    docs = (HealthDocument.query.filter_by(patient_id=patient_id)
            .order_by(HealthDocument.created_at.desc()).all())
    return jsonify(documents=[d.to_dict() for d in docs])


@bp.post("/patients/<int:patient_id>/documents")
@login_required
def create_document(patient_id):
    require_access(patient_id, "documents")
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        abort(400, "Title is required.")
    doc = HealthDocument(
        patient_id=patient_id,
        author_id=g.user.id,
        title=title[:200],
        category=(data.get("category") or "note").strip()[:50],
        body=data.get("body") or "",
    )
    db.session.add(doc)
    db.session.commit()
    return jsonify(document=doc.to_dict()), 201


def _get_doc(doc_id):
    doc = db.session.get(HealthDocument, doc_id)
    if doc is None:
        abort(404, "Not found.")
    require_access(doc.patient_id, "documents")
    return doc


@bp.get("/documents/<int:doc_id>")
@login_required
def get_document(doc_id):
    return jsonify(document=_get_doc(doc_id).to_dict())


@bp.delete("/documents/<int:doc_id>")
@login_required
def delete_document(doc_id):
    doc = _get_doc(doc_id)
    # The patient can delete anything in their records; a provider only what they wrote.
    if g.user.id not in (doc.patient_id, doc.author_id):
        abort(403, "You can only delete documents you wrote.")
    db.session.delete(doc)
    db.session.commit()
    return "", 204
