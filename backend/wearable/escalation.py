"""Alert tiers and escalation (PRD §8).

Tier 0  calm / exercising / recovering / elevated -> logged only
Tier 1  stressed     -> patient nudge
Tier 2  distressed   -> stronger nudge + check-in; family only if family_tier2_alerts is on
Tier 3  emergency    -> Call 911 first. Family: cardiac warning immediately, fall after a 60 s
                        "I'm OK" countdown. Providers are never alerted (they get the report).

At most one open alert / nudge per kind per patient within 15 minutes.
Family notes are generic: never vitals.
"""
import logging
import os
import threading
from datetime import timedelta

from models import db

from . import integrations
from .models import WearableAlert, WearableNudge
from .security import as_utc, utcnow

log = logging.getLogger('mindconnect.wearable')

DEDUPE = timedelta(minutes=15)
FALL_COUNTDOWN_S = int(os.getenv('WEARABLE_FALL_COUNTDOWN', '60'))

NUDGES = {
    1: ('Your body seems tense. Want to take 2 minutes?', '/toolkit#breathing'),
    2: ("You've seemed tense for a while. Are you okay? Let's try 5-4-3-2-1 grounding together.", '/wearable#plan'),
}
FAMILY_NOTES = {
    'distress': 'attuneMIND noticed {name} has seemed very stressed for a while. Consider checking in with them.',
    'fall': 'attuneMIND detected a possible fall. Please check on {name} now.',
    'cardiac_warning': 'attuneMIND detected possible warning signs. Please check on {name} now and call 911 if needed.',
}


def _recent(model, patient_id, kind, now, statuses=None):
    q = model.query.filter_by(patient_id=patient_id, kind=kind).filter(model.created_at >= now - DEDUPE)
    if statuses:
        q = q.filter(model.status.in_(statuses))
    return q.order_by(model.id.desc()).first()


def _nudge(patient_id, tier, kind, message, link, now):
    existing = WearableNudge.query.filter_by(patient_id=patient_id, kind=kind, tier=tier) \
        .filter(WearableNudge.created_at >= now - DEDUPE).first()
    if existing:
        return existing
    nudge = WearableNudge(patient_id=patient_id, tier=tier, kind=kind, message=message, link=link, created_at=now)
    db.session.add(nudge)
    db.session.commit()
    log.info('wearable nudge: patient=%s tier=%s kind=%s', patient_id, tier, kind)
    push_to_phone(nudge)
    return nudge


def _family(patient_id, tier, kind, now, delay=0, name='them'):
    existing = _recent(WearableAlert, patient_id, kind, now, statuses=('pending', 'open'))
    if existing:
        return existing, False
    alert = integrations.notify_family(patient_id, kind, FAMILY_NOTES[kind].format(name=name), tier,
                                       delay_seconds=delay, now=now)
    log.info('wearable family alert: patient=%s tier=%s kind=%s status=%s', patient_id, tier, kind, alert.status)
    return alert, True


def handle(patient_id, reading, profile, now=None, patient_name=None):
    """Run escalation for one new state reading. Returns {"nudge", "alert", "report_due"}."""
    now = now or utcnow()
    tier, state = reading['tier'], reading['state']
    out = {'nudge': None, 'alert': None, 'report_due': False}
    name = (patient_name or 'them').split(' ')[0]
    if tier == 1:
        out['nudge'] = _nudge(patient_id, 1, 'distress', *NUDGES[1], now)
    elif tier == 2:
        out['nudge'] = _nudge(patient_id, 2, 'distress', *NUDGES[2], now)
        if profile.family_tier2_alerts:
            out['alert'], _ = _family(patient_id, 2, 'distress', now, name=name)
        out['report_due'] = True
    elif tier == 3:
        kind = reading.get('kind') or 'cardiac_warning'
        msg = 'Possible fall detected. Call 911 if you are hurt.' if kind == 'fall' else \
            'Warning signs detected. Call 911 now.'
        out['nudge'] = _nudge(patient_id, 3, kind, msg, '/wearable#emergency', now)
        if profile.emergency_alerts:
            delay = FALL_COUNTDOWN_S if kind == 'fall' else 0
            out['alert'], _ = _family(patient_id, 3, kind, now, delay=delay, name=name)
        out['report_due'] = True
    if state and tier >= 2:
        log.info('wearable escalation: patient=%s state=%s tier=%s', patient_id, state, tier)
    return out


def promote_due_alerts(now=None):
    """Send pending fall alerts whose "I'm OK" countdown ended. Runs before every request
    (see __init__.py), so it works even if the patient's tab is closed."""
    now = now or utcnow()
    due = [a for a in WearableAlert.query.filter_by(status='pending').all() if as_utc(a.send_at) <= now]
    for a in due:
        integrations.publish_alert(a)
        log.info('wearable family alert sent after countdown: alert=%s patient=%s', a.id, a.patient_id)
    if due:
        db.session.commit()
    return len(due)


def send_now(patient_id, now=None):
    """Patient pressed Call 911: skip the countdown and alert family right away."""
    now = now or utcnow()
    pending = WearableAlert.query.filter_by(patient_id=patient_id, status='pending').all()
    for a in pending:
        a.send_at = now
        integrations.publish_alert(a)
    if pending:
        db.session.commit()
    return len(pending)


def cancel_pending(patient_id):
    """'I'm OK' during the fall countdown: the family alert is not sent."""
    pending = WearableAlert.query.filter_by(patient_id=patient_id, status='pending').all()
    for a in pending:
        a.status = 'cancelled'
    if pending:
        db.session.commit()
    return len(pending)


def push_to_phone(nudge):
    """Optional: buzz the phone (and the mirrored Apple Watch) via ntfy.sh.
    Set NTFY_TOPIC in .env and subscribe to that topic in the ntfy iPhone app.
    Only the generic nudge text is sent, never vitals or names."""
    topic = (os.getenv('NTFY_TOPIC') or '').strip()
    if not topic:
        return
    server = os.getenv('NTFY_SERVER', 'https://ntfy.sh').rstrip('/')
    base = (os.getenv('PUBLIC_BASE_URL') or '').rstrip('/')
    headers = {'Title': 'attuneMIND', 'Priority': 'urgent' if nudge.tier >= 3 else ('high' if nudge.tier == 2 else 'default'),
               'Tags': 'rotating_light' if nudge.tier >= 3 else 'relieved'}
    if base and nudge.link:
        headers['Click'] = base + nudge.link
    message = nudge.message

    def send():
        try:
            import requests
            requests.post(f'{server}/{topic}', data=message.encode(), headers=headers, timeout=5)
        except Exception:
            log.warning('wearable: phone push failed (nudge=%s)', nudge.id)
    threading.Thread(target=send, daemon=True).start()
