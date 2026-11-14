"""Scenario generator for stage reliability (PRD §6.2 B).

Importable:   generate(scenario, now) -> {"source": "simulator", "sent_at": ..., "samples": [...], "events": [...]}
CLI (run from backend/):
  In-process, straight into the DB:   python -m wearable.simulator --patient 1 --scenario stress_spike
                                      python -m wearable.simulator --demo-patient --scenario fall
  Over HTTP, exactly like the phone:  python -m wearable.simulator --url http://127.0.0.1:5000 --token <device token> --scenario exercise
  Keep streaming every 30 s:          ... --every 30

The same seed gives the same curves, so test runs are repeatable.
"""
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone

SCENARIOS = ('baseline', 'exercise', 'stress_spike', 'sustained_distress', 'fall', 'cardiac_warning', 'recovery')
HISTORY_MIN = 16   # minutes of history per scenario, so the reader's 5/10-minute windows have data


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _profile(scenario, i, n, rng):
    """Values for minute i of n (i = n-1 is 'now')."""
    j = lambda a, b: rng.uniform(a, b)  # noqa: E731
    late = i >= n - 5                  # the last 5 minutes
    calm = dict(heart_rate=j(63, 71), hrv_sdnn=j(42, 50), steps=j(0, 8), active_energy=j(0.4, 1.2), workout_active=0)
    if scenario == 'baseline':
        return calm
    if scenario == 'exercise':
        ramp = min(1.0, i / 6)
        return dict(heart_rate=95 + 48 * ramp + j(-3, 3), hrv_sdnn=j(18, 26), steps=j(125, 165),
                    active_energy=j(9, 12), workout_active=1)
    if scenario == 'stress_spike':
        if not late:
            return calm
        return dict(heart_rate=j(88, 96), hrv_sdnn=j(22, 28), steps=j(0, 5), active_energy=j(0.4, 1.0), workout_active=0)
    if scenario == 'sustained_distress':
        return dict(heart_rate=j(92, 100), hrv_sdnn=j(19, 25), steps=j(0, 4), active_energy=j(0.3, 0.9), workout_active=0)
    if scenario == 'fall':
        return dict(calm, heart_rate=j(80, 95) if late else calm['heart_rate'])
    if scenario == 'cardiac_warning':
        if not late:
            return calm
        return dict(heart_rate=j(156, 166), hrv_sdnn=j(12, 18), steps=j(0, 3), active_energy=j(0.3, 0.8), workout_active=0)
    if scenario == 'recovery':
        t = i / max(1, n - 1)            # stressed -> calm over the window
        return dict(heart_rate=92 - 26 * t + j(-1.5, 1.5), hrv_sdnn=24 + 22 * t + j(-1.5, 1.5),
                    steps=j(0, 6), active_energy=j(0.4, 1.0), workout_active=0)
    raise ValueError(f'Unknown scenario: {scenario}')


def generate(scenario, now=None, seed=42, minutes=HISTORY_MIN):
    if scenario not in SCENARIOS:
        raise ValueError(f'Unknown scenario: {scenario}. Pick one of: {", ".join(SCENARIOS)}')
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    rng = random.Random(f'{scenario}-{seed}')
    samples = [{'type': 'resting_hr', 'value': 65, 'ts': _iso(now - timedelta(minutes=minutes))}]
    for i in range(minutes):
        ts = now - timedelta(minutes=minutes - 1 - i)
        for typ, value in _profile(scenario, i, minutes, rng).items():
            samples.append({'type': typ, 'value': round(value, 1), 'ts': _iso(ts)})
    events = []
    if scenario == 'fall':
        events.append({'type': 'fall_detected', 'ts': _iso(now)})
    if scenario == 'cardiac_warning':
        events.append({'type': 'self_report', 'ts': _iso(now), 'meta': {'symptom': 'chest_pain'}})
    return {'source': 'simulator', 'sent_at': _iso(now), 'samples': samples, 'events': events}


# ---------- CLI ----------

def _post_http(url, token, payload):
    import requests
    r = requests.post(url.rstrip('/') + '/api/wearable/ingest', json=payload,
                      headers={'X-Device-Token': token}, timeout=10)
    try:
        body = r.json()
    except ValueError:
        body = {'raw': r.text[:200]}
    return r.status_code, body


def _run_in_process(patient_id, scenario, seed):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # backend/
    from app import app  # backend/app.py
    from models import User
    from . import service
    with app.app_context():
        if patient_id is None:   # --demo-patient: the DEV_LOGIN demo user
            user = User.query.filter_by(google_sub='dev-demo-user').first()
            if user is None:
                return 1, {'error': 'No demo patient yet: start the app and open /wearable/dev-login/patient once.'}
            patient_id = user.id
        result = service.run_scenario(patient_id, scenario, seed=seed)
    return 200, result


def main(argv=None):
    p = argparse.ArgumentParser(description='AttuneMind wearable simulator')
    p.add_argument('--scenario', required=True, choices=SCENARIOS)
    p.add_argument('--patient', type=int, help='patient (user) id, writes straight to the local DB')
    p.add_argument('--demo-patient', action='store_true', help='use the DEV_LOGIN demo patient')
    p.add_argument('--url', help='app base URL, e.g. http://127.0.0.1:5000 or your tunnel URL')
    p.add_argument('--token', help='device token from the My Watch page (with --url)')
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--every', type=int, default=0, help='repeat every N seconds (Ctrl+C to stop)')
    p.add_argument('--dry-run', action='store_true', help='print the payload and exit')
    a = p.parse_args(argv)

    if a.dry_run:
        print(json.dumps(generate(a.scenario, seed=a.seed), indent=2))
        return 0
    if not a.patient and not a.demo_patient and not (a.url and a.token):
        p.error('use --patient ID, --demo-patient, or --url URL --token TOKEN')
    while True:
        if a.patient or a.demo_patient:
            status, body = _run_in_process(a.patient, a.scenario, a.seed)
        else:
            status, body = _post_http(a.url, a.token, generate(a.scenario, seed=a.seed))
        state = (body.get('state') or {}) if isinstance(body, dict) else {}
        alert = body.get('alert') if isinstance(body, dict) else None
        print(f'[{datetime.now():%H:%M:%S}] {a.scenario}: HTTP {status} -> state={state.get("state")} '
              f'tier={state.get("tier")} alert={alert.get("kind") + "/" + alert.get("status") if alert else None}'
              + (f' error={body.get("error")}' if isinstance(body, dict) and body.get('error') else ''))
        if not a.every:
            return 0 if status == 200 else 1
        time.sleep(a.every)


if __name__ == '__main__':
    sys.exit(main())
