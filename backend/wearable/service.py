"""Wearable business logic shared by routes, the simulator CLI and tests.

ingest -> validate -> store (dedupe) -> reader.classify -> StateReading -> escalation -> report
"""
import logging
import math
import os
from datetime import datetime, timedelta, timezone

from models import User, db

from . import escalation, integrations, reader, report, simulator
from .ai_explain import maybe_explain
from .models import (AIUsageLog, StateReading, VitalSample, WearableAlert, WearableDevice, WearableEvent,
                     WearableNudge, WearableProfile, WearableReport)
from .security import MAX_SAMPLES, as_utc, utcnow

log = logging.getLogger('mindconnect.wearable')

REPLAY_WINDOW = timedelta(minutes=10)
FUTURE_SKEW = timedelta(minutes=5)
REPORT_DEDUPE = timedelta(minutes=15)
PLAUSIBLE = {
    'heart_rate': (20, 260), 'hrv_sdnn': (1, 400), 'resting_hr': (25, 150), 'steps': (0, 100000),
    'active_energy': (0, 10000), 'workout_active': (0, 1),
}
CORRECTIONS = ('exercising', 'not_okay', 'im_ok')


class PayloadError(ValueError):
    pass


def parse_ts(value, field='ts'):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        s = value.strip().replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise PayloadError(f'{field} must be an ISO 8601 date, e.g. 2026-11-14T15:02:11Z') from None
    else:
        raise PayloadError(f'{field} is required')
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _coerce(value, typ):
    try:
        v = float(str(value).strip().split(' ')[0]) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        raise PayloadError(f'value for {typ} must be a number') from None
    if math.isnan(v) or math.isinf(v):
        raise PayloadError(f'value for {typ} must be a real number')
    lo, hi = PLAUSIBLE[typ]
    if not lo <= v <= hi:
        raise PayloadError(f'value for {typ} is out of range ({lo}-{hi})')
    return v


def validate_payload(data, now=None):
    """Strict schema (PRD §6.3). Also accepts a flat format that is much easier to build in
    iOS Shortcuts: {"sent_at": "...", "heart_rate": 72, "hrv_sdnn": 41, "ts": "..."}"""
    now = now or utcnow()
    if not isinstance(data, dict):
        raise PayloadError('Body must be a JSON object')
    sent_at = parse_ts(data.get('sent_at'), 'sent_at')
    if abs(now - sent_at) > REPLAY_WINDOW:
        raise PayloadError('sent_at is more than 10 minutes off the server clock (replay protection)')

    raw_samples = data.get('samples')
    if raw_samples is None:   # flat Shortcut format
        flat_ts = data.get('ts') or data.get('sent_at')
        raw_samples = [{'type': k, 'value': data[k], 'ts': flat_ts} for k in reader.SAMPLE_TYPES
                       if k in data and data[k] not in (None, '')]
        unknown = set(data) - set(reader.SAMPLE_TYPES) - {'sent_at', 'ts', 'source', 'events'}
        if unknown:
            raise PayloadError(f'Unknown field(s): {", ".join(sorted(unknown))}')
    if not isinstance(raw_samples, list):
        raise PayloadError('samples must be a list')
    raw_events = data.get('events') or []
    if not isinstance(raw_events, list):
        raise PayloadError('events must be a list')
    if len(raw_samples) + len(raw_events) > MAX_SAMPLES:
        raise PayloadError(f'Too many samples (max {MAX_SAMPLES} per request)')
    if not raw_samples and not raw_events:
        raise PayloadError('No samples or events in the payload')

    samples = []
    for s in raw_samples:
        if not isinstance(s, dict):
            raise PayloadError('Each sample must be an object')
        typ = s.get('type')
        if typ not in reader.SAMPLE_TYPES:
            raise PayloadError(f'Unknown sample type: {typ!r}')
        ts = parse_ts(s.get('ts') or data.get('sent_at'))
        if ts - now > FUTURE_SKEW:
            raise PayloadError('Sample timestamp is in the future')
        samples.append({'type': typ, 'value': _coerce(s.get('value'), typ), 'ts': ts.replace(microsecond=0)})

    events = []
    for e in raw_events:
        if not isinstance(e, dict) or e.get('type') not in reader.EVENT_TYPES:
            raise PayloadError(f'Unknown event type: {e.get("type") if isinstance(e, dict) else e!r}')
        meta = e.get('meta') or {}
        if e['type'] == 'self_report' and meta.get('symptom') not in reader.SYMPTOMS:
            raise PayloadError(f'self_report symptom must be one of: {", ".join(reader.SYMPTOMS)}')
        events.append({'type': e['type'], 'ts': parse_ts(e.get('ts') or data.get('sent_at')),
                       'meta': {'symptom': meta['symptom']} if 'symptom' in meta else None})
    return samples, events


def ensure_profile(patient_id):
    profile = db.session.get(WearableProfile, patient_id)
    if profile is None:
        profile = WearableProfile(patient_id=patient_id)
        db.session.add(profile)
        db.session.commit()
    return profile


def store(patient_id, samples, events, source):
    """Insert samples, skipping duplicates on (patient, type, ts). Out-of-order is fine."""
    inserted = dupes = 0
    if samples:
        lo, hi = min(s['ts'] for s in samples), max(s['ts'] for s in samples)
        existing = {(r.type, as_utc(r.ts)) for r in db.session.query(VitalSample.type, VitalSample.ts)
                    .filter(VitalSample.patient_id == patient_id, VitalSample.ts >= lo, VitalSample.ts <= hi)}
        for s in samples:
            key = (s['type'], s['ts'])
            if key in existing:
                dupes += 1
                continue
            existing.add(key)
            db.session.add(VitalSample(patient_id=patient_id, type=s['type'], value_enc=s['value'],
                                       ts=s['ts'], source=source))
            inserted += 1
    for e in events:
        dup = WearableEvent.query.filter_by(patient_id=patient_id, type=e['type'], ts=e['ts']).first()
        if dup:
            dupes += 1
            continue
        db.session.add(WearableEvent(patient_id=patient_id, type=e['type'], ts=e['ts'], meta_enc=e['meta'],
                                     source=source))
        inserted += 1
    db.session.commit()
    log.info('wearable ingest: patient=%s source=%s inserted=%s duplicates=%s', patient_id, source, inserted, dupes)
    return inserted, dupes


def _clear_simulator_window(patient_id, since):
    VitalSample.query.filter(VitalSample.patient_id == patient_id, VitalSample.source == 'simulator',
                             VitalSample.ts >= since).delete(synchronize_session=False)
    WearableEvent.query.filter(WearableEvent.patient_id == patient_id, WearableEvent.source == 'simulator',
                               WearableEvent.ts >= since - timedelta(minutes=15)).delete(synchronize_session=False)
    db.session.commit()


def ingest(patient_id, data, source=None, now=None):
    now = now or utcnow()
    samples, events = validate_payload(data, now)
    source = source or str(data.get('source') or 'apple_watch')[:32]
    if source == 'simulator' and samples:
        # Switching demo scenarios replaces the previous scenario's simulated window.
        _clear_simulator_window(patient_id, min(s['ts'] for s in samples))
    inserted, dupes = store(patient_id, samples, events, source)
    reading, alert = evaluate(patient_id, now)
    return {'state': reading, 'alert': alert, 'inserted': inserted, 'duplicates': dupes}


def evaluate(patient_id, now=None):
    now = now or utcnow()
    profile = ensure_profile(patient_id)
    samples = [{'type': s.type, 'value': s.value_enc, 'ts': as_utc(s.ts)} for s in
               VitalSample.query.filter(VitalSample.patient_id == patient_id,
                                        VitalSample.ts >= now - timedelta(days=7)).all()
               if s.type == 'resting_hr' or as_utc(s.ts) >= now - timedelta(minutes=75)]
    events = [{'type': e.type, 'ts': as_utc(e.ts), 'meta': e.meta_enc} for e in
              WearableEvent.query.filter(WearableEvent.patient_id == patient_id,
                                         WearableEvent.ts >= now - timedelta(minutes=30))]
    reading = reader.classify(samples, events, {'resting_hr': profile.baseline_resting_hr,
                                                 'hrv': profile.baseline_hrv}, now)
    reading['explanation'] = maybe_explain(patient_id, reading, profile)
    db.session.add(StateReading(patient_id=patient_id, state=reading['state'], kind=reading['kind'],
                                confidence=reading['confidence'], ts=now,
                                reasons_enc={'reasons': reading['reasons'], 'explanation': reading['explanation'],
                                             'metrics': reading['metrics']}))
    db.session.commit()
    patient = db.session.get(User, patient_id)
    result = escalation.handle(patient_id, reading, profile, now, patient_name=patient.name if patient else None)
    if result['report_due']:
        last = WearableReport.query.filter_by(patient_id=patient_id).order_by(WearableReport.id.desc()).first()
        if last is None or now - as_utc(last.created_at) > REPORT_DEDUPE:
            generate_report(patient_id, now)
    alert = result['alert'].to_dict() if result['alert'] else None
    return {**reading, 'ts': now.isoformat()}, alert


def generate_report(patient_id, now=None):
    title, body = report.build_report(patient_id, now=now)
    return integrations.save_provider_report(patient_id, title, body)


def run_scenario(patient_id, scenario, seed=42, now=None):
    now = now or utcnow()
    payload = simulator.generate(scenario, now=now, seed=seed)
    return ingest(patient_id, payload, source='simulator', now=now)


def add_patient_event(patient_id, typ, meta=None, now=None):
    now = now or utcnow()
    db.session.add(WearableEvent(patient_id=patient_id, type=typ, ts=now, meta_enc=meta, source='patient'))
    db.session.commit()
    cancelled = escalation.cancel_pending(patient_id) if typ == 'im_ok' else 0
    reading, alert = evaluate(patient_id, now)
    return {'state': reading, 'alert': alert, 'cancelled_alerts': cancelled}


# ---------- reads ----------

def latest_state(patient_id):
    escalation.promote_due_alerts()
    r = StateReading.query.filter_by(patient_id=patient_id).order_by(StateReading.id.desc()).first()
    latest = {}
    for typ in ('heart_rate', 'hrv_sdnn', 'resting_hr', 'steps'):
        s = VitalSample.query.filter_by(patient_id=patient_id, type=typ).order_by(VitalSample.ts.desc()).first()
        if s:
            latest[typ] = {'value': s.value_enc, 'ts': as_utc(s.ts).isoformat(), 'source': s.source}
    pending = WearableAlert.query.filter_by(patient_id=patient_id, status='pending').order_by(WearableAlert.id.desc()).first()
    recent_alert = WearableAlert.query.filter_by(patient_id=patient_id).filter(WearableAlert.status != 'cancelled') \
        .order_by(WearableAlert.id.desc()).first()
    nudge = WearableNudge.query.filter_by(patient_id=patient_id, seen_at=None).order_by(WearableNudge.id.desc()).first()
    state = None
    if r:
        extra = r.reasons_enc or {}
        state = {'state': r.state, 'kind': r.kind, 'tier': reader.TIER[r.state], 'confidence': r.confidence,
                 'reasons': extra.get('reasons', []), 'explanation': extra.get('explanation'),
                 'metrics': extra.get('metrics', {}), 'ts': as_utc(r.ts).isoformat()}
    return {'state': state, 'latest': latest,
            'pending_alert': pending.to_dict() if pending else None,
            'last_family_alert': recent_alert.to_dict() if recent_alert else None,
            'nudge': nudge.to_dict() if nudge else None,
            'server_time': utcnow().isoformat()}


RANGES = {'1h': timedelta(hours=1), '6h': timedelta(hours=6), '24h': timedelta(hours=24), '7d': timedelta(days=7)}


def timeline(patient_id, rng='24h'):
    since = utcnow() - RANGES.get(rng, RANGES['24h'])
    out = {t: [] for t in ('heart_rate', 'hrv_sdnn', 'steps')}
    for s in VitalSample.query.filter(VitalSample.patient_id == patient_id, VitalSample.ts >= since,
                                      VitalSample.type.in_(tuple(out))).order_by(VitalSample.ts):
        out[s.type].append({'ts': as_utc(s.ts).isoformat(), 'value': s.value_enc, 'source': s.source})
    states = [{'ts': as_utc(r.ts).isoformat(), 'state': r.state} for r in
              StateReading.query.filter(StateReading.patient_id == patient_id, StateReading.ts >= since)
              .order_by(StateReading.ts)]
    return {'range': rng if rng in RANGES else '24h', 'series': out, 'states': states}


def resolution_plan(patient_id, state):
    """Short step plan for the current episode, with a projected recovery time from past check-ins."""
    if not state or state.get('state') not in ('elevated', 'stressed', 'distressed'):
        return None
    best, minutes = None, None
    rated = [c for c in integrations.get_checkins(patient_id) if c.stress_before is not None and c.stress_after is not None]
    if rated:
        by = {}
        for c in rated:
            by.setdefault(c.activity, []).append(c.stress_after - c.stress_before)
        best = min(by, key=lambda a: sum(by[a]) / len(by[a]))
    anchors = {'breathing': '/toolkit#breathing', 'grounding': '/toolkit#grounding',
               'thought-record': '/toolkit#thought-record'}
    first = best if best in anchors else 'breathing'
    minutes = 10 if state['state'] == 'distressed' else 5
    steps = [
        {'text': 'Pause and notice: you are safe right now. Unclench your jaw and drop your shoulders.', 'link': None},
        {'text': f'Do {first.replace("-", " ")} for 2 minutes' + (' (it has helped you most before).' if best else '.'),
         'link': anchors[first]},
        {'text': 'Then try 5-4-3-2-1 grounding to bring your attention back to the room.', 'link': '/toolkit#grounding'},
        {'text': 'If it is still hard, talk it through in Chat or reach out to someone you trust.', 'link': '/chat'},
    ]
    return {'steps': steps, 'projected_minutes': minutes,
            'based_on': f'{len(rated)} past check-in(s)' if rated else 'typical recovery times'}


def privacy_summary(patient_id):
    from .models import AuditLog
    from .security import KEY_SOURCE, ai_allowed_for_wearable, ai_tier, get_fernet, https_mode
    get_fernet()
    profile = ensure_profile(patient_id)
    week = utcnow() - timedelta(days=7)
    viewers = AuditLog.query.filter_by(patient_id=patient_id).order_by(AuditLog.id.desc()).limit(40).all()
    tier = ai_tier()
    return {
        'encryption': {'at_rest': 'Fernet (AES-128-CBC + HMAC-SHA256)', 'key_source': KEY_SOURCE,
                       'in_transit': 'HTTPS / TLS via Cloudflare Tunnel', 'https_mode': https_mode()},
        'audit': [a.to_dict() for a in viewers],
        'ai': {'provider': 'Google Gemini', 'model': os.getenv('GEMINI_CHAT_MODEL', 'gemini-3.8-flash'),
               'tier': tier, 'enabled_for_wearable': ai_allowed_for_wearable() and profile.ai_explanations,
               'used_to_train': None if tier == 'free' else False,
               'fields_sent': ['hr_pct_above_rest', 'hrv_pct_below', 'movement', 'state'],
               'calls_this_week': AIUsageLog.query.filter(AIUsageLog.patient_id == patient_id,
                                                          AIUsageLog.ts >= week).count(),
               'patient_opt_in': profile.ai_explanations},
        'profile': profile.to_dict(),
        'devices': [d.to_dict() for d in WearableDevice.query.filter_by(patient_id=patient_id)],
    }


def export_data(patient_id):
    from .models import AuditLog
    profile = ensure_profile(patient_id)
    iso = lambda d: as_utc(d).isoformat() if d else None  # noqa: E731
    return {
        'exported_at': utcnow().isoformat(),
        'patient_id': patient_id,
        'profile': profile.to_dict(),
        'devices': [d.to_dict() for d in WearableDevice.query.filter_by(patient_id=patient_id)],
        'samples': [{'type': s.type, 'value': s.value_enc, 'ts': iso(s.ts), 'source': s.source}
                    for s in VitalSample.query.filter_by(patient_id=patient_id).order_by(VitalSample.ts)],
        'events': [{'type': e.type, 'ts': iso(e.ts), 'meta': e.meta_enc, 'source': e.source}
                   for e in WearableEvent.query.filter_by(patient_id=patient_id).order_by(WearableEvent.ts)],
        'states': [{'state': r.state, 'kind': r.kind, 'confidence': r.confidence, 'ts': iso(r.ts),
                    **(r.reasons_enc or {})} for r in StateReading.query.filter_by(patient_id=patient_id)],
        'alerts': [a.to_dict() for a in WearableAlert.query.filter_by(patient_id=patient_id)],
        'reports': [{'title': r.title, 'body': r.body_enc, 'created_at': iso(r.created_at)}
                    for r in WearableReport.query.filter_by(patient_id=patient_id)],
        'audit_log': [a.to_dict() for a in AuditLog.query.filter_by(patient_id=patient_id).order_by(AuditLog.id)],
    }


def delete_all(patient_id, keep_profile=False, keep_devices=False):
    """Removes samples, events, states, devices, nudges, alerts, reports and the profile.
    The append-only audit log is kept (it records the deletion itself)."""
    counts = {}
    for model in (VitalSample, WearableEvent, StateReading, WearableNudge, WearableAlert, WearableReport,
                  AIUsageLog) + (() if keep_devices else (WearableDevice,)):
        counts[model.__tablename__] = model.query.filter_by(patient_id=patient_id).delete(synchronize_session=False)
    if not keep_profile:
        counts['wearable_profile'] = WearableProfile.query.filter_by(patient_id=patient_id).delete(synchronize_session=False)
    db.session.commit()
    return counts
