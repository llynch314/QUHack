"""Provider report builder (PRD §9). Providers get this report, never live alerts.

build_report(patient_id) -> (title, markdown body). Saved through integrations.save_provider_report.
"""
from collections import defaultdict
from datetime import timedelta

from . import integrations
from .models import StateReading, VitalSample, WearableEvent
from .security import as_utc, utcnow

STRESS_STATES = ('stressed', 'distressed', 'emergency')
GAP = timedelta(minutes=10)


def _fmt(dt):
    return as_utc(dt).strftime('%Y-%m-%d %H:%M UTC')


def _part_of_day(dt):
    h = as_utc(dt).hour
    return 'night' if h < 6 else 'morning' if h < 12 else 'afternoon' if h < 18 else 'evening'


def _group(readings, predicate):
    """Consecutive readings matching predicate, split by gaps > 10 min."""
    groups, cur = [], []
    for r in readings:
        if predicate(r):
            if cur and as_utc(r.ts) - as_utc(cur[-1].ts) > GAP:
                groups.append(cur)
                cur = []
            cur.append(r)
        elif cur:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def build_report(patient_id, days=7, now=None):
    now = now or utcnow()
    since = now - timedelta(days=days)
    readings = StateReading.query.filter(StateReading.patient_id == patient_id, StateReading.ts >= since) \
        .order_by(StateReading.ts).all()
    events = WearableEvent.query.filter(WearableEvent.patient_id == patient_id, WearableEvent.ts >= since) \
        .order_by(WearableEvent.ts).all()

    episodes = _group(readings, lambda r: r.state in STRESS_STATES)
    exercise = _group(readings, lambda r: r.state == 'exercising')
    emergencies = []
    for grp in _group(readings, lambda r: r.state == 'emergency'):
        emergencies.append((grp[0].kind or 'cardiac_warning', grp[0].ts))

    lines = [f'# Wearable report', '',
             f'Period: {_fmt(since)} to {_fmt(now)} (last {days} days). Generated automatically by AttuneMind '
             'from the patient\'s wearable. This is a summary for the next appointment, not a diagnosis.', '']

    lines += ['## Stress episodes', '']
    if not episodes:
        lines.append('No stress episodes detected.')
    else:
        rank = {'stressed': 1, 'distressed': 2, 'emergency': 3}
        total_min = 0
        by_part = defaultdict(int)
        lines += ['| Start | Duration | Peak state | Time of day |', '|---|---|---|---|']
        for ep in episodes:
            dur = max(1, round((as_utc(ep[-1].ts) - as_utc(ep[0].ts)).total_seconds() / 60))
            total_min += dur
            peak = max(ep, key=lambda r: rank[r.state]).state
            by_part[_part_of_day(ep[0].ts)] += 1
            lines.append(f'| {_fmt(ep[0].ts)} | ~{dur} min | {peak} | {_part_of_day(ep[0].ts)} |')
        lines += ['', f'**{len(episodes)} episode(s)**, about {total_min} min in total. Most common time of day: '
                  f'{max(by_part, key=by_part.get)}.']
    lines.append('')

    lines += ['## Exercise correctly ignored', '',
              f'{len(exercise)} exercise period(s) with a high heart rate were recognised as exercise and did '
              'not trigger a stress alert.', '']

    lines += ['## Falls and cardiac warnings', '']
    if emergencies:
        for kind, ts in emergencies:
            lines.append(f'- {_fmt(ts)}: {"possible fall" if kind == "fall" else "cardiac warning signs"} '
                         '(patient shown Call 911; family alerted per patient settings)')
    else:
        lines.append('None.')
    lines.append('')

    lines += ['## What helped (patient check-ins)', '']
    diffs = defaultdict(list)
    for c in integrations.get_checkins(patient_id):
        if c.stress_before is not None and c.stress_after is not None and as_utc(c.created_at) >= since:
            diffs[c.activity].append(c.stress_after - c.stress_before)
    if diffs:
        for activity, d in sorted(diffs.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
            lines.append(f'- {activity.replace("-", " ").capitalize()}: {sum(d) / len(d):+.1f} average stress change '
                         f'({len(d)} check-in(s))')
    else:
        lines.append('No before/after check-ins in this period.')
    lines.append('')

    lines += ['## Patient corrections and self-reports', '']
    counts = defaultdict(int)
    for e in events:
        if e.type == 'self_report':
            counts[f'self-report: {(e.meta_enc or {}).get("symptom", "other").replace("_", " ")}'] += 1
        elif e.type in ('exercising', 'not_okay', 'im_ok'):
            counts[{'exercising': '"I\'m exercising"', 'not_okay': '"I\'m not okay"', 'im_ok': '"I\'m OK"'}[e.type]] += 1
    lines += [f'- {k}: {v}' for k, v in counts.items()] or ['None.']
    lines.append('')

    lines += ['## Resting heart rate and HRV trend (daily average)', '', '| Day | Resting HR | HRV (SDNN, ms) |', '|---|---|---|']
    daily = defaultdict(lambda: {'resting_hr': [], 'hrv_sdnn': []})
    for s in VitalSample.query.filter(VitalSample.patient_id == patient_id, VitalSample.ts >= since,
                                      VitalSample.type.in_(('resting_hr', 'hrv_sdnn'))):
        daily[as_utc(s.ts).strftime('%Y-%m-%d')][s.type].append(float(s.value_enc))
    avg = lambda xs: f'{sum(xs) / len(xs):.0f}' if xs else '-'  # noqa: E731
    rows = [f'| {d} | {avg(v["resting_hr"])} | {avg(v["hrv_sdnn"])} |' for d, v in sorted(daily.items())]
    lines += rows or ['| - | - | - |']

    title = f'Wearable report {now.strftime("%Y-%m-%d %H:%M")} UTC'
    return title, '\n'.join(lines) + '\n'
