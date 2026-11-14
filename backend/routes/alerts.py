"""Urgent alerts (panic attack, meltdown, crisis). Visible to the patient and linked family."""
from flask import Blueprint, abort, g, jsonify, request

from auth import login_required, require_access, roles_required
from models import ALERT_KINDS, Alert, CareLink, db, utcnow

bp = Blueprint("alerts", __name__, url_prefix="/api")


def create_alert(patient_id, kind, source, note=""):
    alert = Alert(patient_id=patient_id, kind=kind, source=source, note=note[:500])
    db.session.add(alert)
    db.session.commit()
    return alert


@bp.get("/alerts")
@login_required
def my_alerts():
    """Patient: their own alerts. Family: alerts for every patient they're linked to."""
    if g.user.role == "patient":
        patient_ids = [g.user.id]
    elif g.user.role == "family":
        patient_ids = [l.patient_id for l in CareLink.query.filter_by(member_id=g.user.id)]
    else:
        abort(403, "Health providers don't have access to alerts.")
    query = Alert.query.filter(Alert.patient_id.in_(patient_ids))
    if request.args.get("unacknowledged") in ("1", "true"):
        query = query.filter(Alert.acknowledged_at.is_(None))
    alerts = query.order_by(Alert.created_at.desc()).limit(100).all()
    return jsonify(alerts=[a.to_dict() for a in alerts])


@bp.get("/patients/<int:patient_id>/alerts")
@login_required
def patient_alerts(patient_id):
    require_access(patient_id, "alerts")
    alerts = (Alert.query.filter_by(patient_id=patient_id)
              .order_by(Alert.created_at.desc()).limit(100).all())
    return jsonify(alerts=[a.to_dict() for a in alerts])


@bp.post("/alerts/sos")
@roles_required("patient")
def sos():
    """The patient's own 'I need help' button."""
    data = request.get_json(silent=True) or {}
    kind = data.get("kind", "other")
    if kind not in ALERT_KINDS:
        abort(400, f"kind must be one of: {', '.join(ALERT_KINDS)}")
    alert = create_alert(g.user.id, kind, "manual", data.get("note") or "")
    return jsonify(alert=alert.to_dict()), 201


@bp.post("/alerts/<int:alert_id>/acknowledge")
@login_required
def acknowledge(alert_id):
    alert = db.session.get(Alert, alert_id)
    if alert is None:
        abort(404, "Not found.")
    require_access(alert.patient_id, "alerts")
    if alert.acknowledged_at is None:
        alert.acknowledged_at = utcnow()
        alert.acknowledged_by_id = g.user.id
        db.session.commit()
    return jsonify(alert=alert.to_dict())
