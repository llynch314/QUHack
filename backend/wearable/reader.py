"""Emotional-state reader (PRD §7). Pure Python: no Flask, no database, no AI.

classify(samples, events, baseline, now) -> {state, kind, tier, confidence, reasons, explanation, metrics}

samples: [{"type": "heart_rate", "value": 72.0, "ts": datetime}, ...]
events:  [{"type": "fall_detected" | "self_report" | "exercising" | "not_okay" | "im_ok", "ts": datetime, "meta": {...}}]
baseline: {"resting_hr": 65, "hrv": 45}

A high heart rate on its own never means distress: movement context is checked first.
"""
from datetime import datetime, timedelta, timezone

STATES = ('calm', 'elevated', 'stressed', 'distressed', 'exercising', 'recovering', 'emergency')
TIER = {'calm': 0, 'elevated': 0, 'exercising': 0, 'recovering': 0, 'stressed': 1, 'distressed': 2, 'emergency': 3}
SAMPLE_TYPES = ('heart_rate', 'hrv_sdnn', 'resting_hr', 'steps', 'active_energy', 'workout_active')
EVENT_TYPES = ('fall_detected', 'self_report')
CARDIAC_SYMPTOMS = ('chest_pain', 'cant_breathe', 'fainting')
SYMPTOMS = CARDIAC_SYMPTOMS + ('panic',)

# Thresholds (PRD §7.1)
STRESS_HR_PCT = 25           # HR >= 25% above resting
STRESS_HRV_PCT = 30          # HRV >= 30% below baseline
WORSE_HR_PCT = 45
WORSE_HRV_PCT = 50
ELEVATED_HR_PCT = 15
ELEVATED_HRV_PCT = 20
EXERCISE_STEPS_PER_MIN = 60
EXERCISE_ENERGY_PER_MIN = 4  # kcal/min, about a brisk walk
LOW_MOVE_STEPS_PER_MIN = 20
EMERGENCY_HIGH_HR = 150
EMERGENCY_LOW_HR = 40
EXERCISE_HOLD = timedelta(minutes=20)
EMERGENCY_WINDOW = timedelta(minutes=10)
RECOVERY_WINDOW = timedelta(minutes=10)
NOT_OKAY_WINDOW = timedelta(minutes=15)
STALE_AFTER = timedelta(minutes=15)


def _utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _vals(samples, typ, start, end):
    return [s['value'] for s in samples if s['type'] == typ and start < s['ts'] <= end]


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _pct_above(value, base):
    return round((value - base) / base * 100) if value is not None and base else None


def _pct_below(value, base):
    return round((base - value) / base * 100) if value is not None and base else None


class _Ctx:
    def __init__(self, samples, baseline, now):
        self.s = samples
        self.now = now
        rest = _vals(samples, 'resting_hr', now - timedelta(days=7), now)
        self.resting = rest[-1] if rest else float(baseline.get('resting_hr') or 65)
        self.base_hrv = float(baseline.get('hrv') or 45)

    def hr(self, t, minutes=5):
        return _mean(_vals(self.s, 'heart_rate', t - timedelta(minutes=minutes), t))

    def hrv(self, t):
        recent = _vals(self.s, 'hrv_sdnn', t - timedelta(minutes=5), t)
        if recent:
            return _mean(recent)
        older = _vals(self.s, 'hrv_sdnn', t - timedelta(minutes=60), t)
        return older[-1] if older else None

    def per_min(self, typ, t, minutes):
        vals = _vals(self.s, typ, t - timedelta(minutes=minutes), t)
        return sum(vals) / minutes if vals else 0.0

    def workout(self, t):
        vals = _vals(self.s, 'workout_active', t - timedelta(minutes=5), t)
        return bool(vals) and vals[-1] >= 1

    def moving(self, t):
        return (self.workout(t)
                or self.per_min('steps', t, 5) > EXERCISE_STEPS_PER_MIN
                or self.per_min('active_energy', t, 5) >= EXERCISE_ENERGY_PER_MIN)

    def low_movement(self, t):
        return (not self.workout(t)
                and self.per_min('steps', t, 3) < LOW_MOVE_STEPS_PER_MIN
                and self.per_min('active_energy', t, 3) < EXERCISE_ENERGY_PER_MIN / 2)

    def stress_metrics(self, t):
        hr, hrv = self.hr(t), self.hrv(t)
        return _pct_above(hr, self.resting), _pct_below(hrv, self.base_hrv)

    def stressed_at(self, t):
        hr_pct, hrv_pct = self.stress_metrics(t)
        return (hr_pct is not None and hrv_pct is not None and hr_pct >= STRESS_HR_PCT
                and hrv_pct >= STRESS_HRV_PCT and self.low_movement(t))


def _latest_event(events, typ, since, symptom=None):
    found = [e for e in events if e['type'] == typ and e['ts'] >= since
             and (symptom is None or (e.get('meta') or {}).get('symptom') in symptom)]
    return max(found, key=lambda e: e['ts']) if found else None


def _cleared_by_im_ok(events, ev):
    return any(e['type'] == 'im_ok' and e['ts'] >= ev['ts'] for e in events)


def classify(samples, events, baseline, now=None):
    now = _utc(now or datetime.now(timezone.utc))
    samples = sorted(({**s, 'ts': _utc(s['ts']), 'value': float(s['value'])} for s in samples
                      if _utc(s['ts']) <= now), key=lambda s: s['ts'])
    events = [{**e, 'ts': _utc(e['ts'])} for e in events if _utc(e['ts']) <= now]
    c = _Ctx(samples, baseline, now)

    hr_latest_vals = _vals(samples, 'heart_rate', now - timedelta(minutes=5), now)
    hr_latest = hr_latest_vals[-1] if hr_latest_vals else None
    hr_pct, hrv_pct = c.stress_metrics(now)
    moving = c.moving(now)
    metrics = {
        'hr': round(c.hr(now)) if c.hr(now) is not None else None,
        'hrv': round(c.hrv(now)) if c.hrv(now) is not None else None,
        'resting_hr': round(c.resting),
        'hr_pct_above_rest': hr_pct,
        'hrv_pct_below': hrv_pct,
        'movement': 'high' if moving else ('low' if c.low_movement(now) else 'some'),
    }

    def result(state, confidence, reasons, kind=None):
        return {'state': state, 'kind': kind, 'tier': TIER[state], 'confidence': round(confidence, 2),
                'reasons': reasons, 'explanation': _explain(state, kind), 'metrics': metrics}

    # 1. Emergencies first (Tier 3). Never a diagnosis: "warning signs".
    fall = _latest_event(events, 'fall_detected', now - EMERGENCY_WINDOW)
    if fall and not _cleared_by_im_ok(events, fall):
        return result('emergency', 0.95, ['Your watch detected a possible fall.'], kind='fall')
    symptom = _latest_event(events, 'self_report', now - EMERGENCY_WINDOW, CARDIAC_SYMPTOMS)
    if symptom and not _cleared_by_im_ok(events, symptom):
        label = symptom['meta']['symptom'].replace('_', ' ').replace('cant', "can't")
        return result('emergency', 0.9, [f'You reported: {label}.'], kind='cardiac_warning')
    recent_ok = _latest_event(events, 'im_ok', now - EMERGENCY_WINDOW)
    if hr_latest is not None and not recent_ok:
        if hr_latest > EMERGENCY_HIGH_HR and not moving and c.low_movement(now):
            return result('emergency', 0.8, [f'Heart rate above {EMERGENCY_HIGH_HR} while at rest.'],
                          kind='cardiac_warning')
        if hr_latest < EMERGENCY_LOW_HR:
            return result('emergency', 0.8, [f'Heart rate below {EMERGENCY_LOW_HR}.'], kind='cardiac_warning')

    if not samples or c.hr(now, minutes=int(STALE_AFTER.total_seconds() // 60)) is None:
        return result('calm', 0.2, ['No heart-rate data in the last 15 minutes yet.'])

    # 2. Exercise beats stress.
    if _latest_event(events, 'exercising', now - EXERCISE_HOLD):
        return result('exercising', 0.9, ["You told us you're exercising, so stress alerts are paused for 20 minutes."])
    if moving:
        why = []
        if c.workout(now):
            why.append('A workout is active on your watch.')
        steps = c.per_min('steps', now, 5)
        if steps > EXERCISE_STEPS_PER_MIN:
            why.append(f'About {round(steps)} steps a minute.')
        if c.per_min('active_energy', now, 5) >= EXERCISE_ENERGY_PER_MIN:
            why.append('Active energy is clearly up.')
        if hr_pct is not None and hr_pct > 0:
            why.append(f'HR {hr_pct}% above your resting rate, which fits the activity.')
        return result('exercising', 0.85, why)

    # 3. Recovering: exercise ended within the last 10 minutes and HR is still coming down.
    ended_recently = any(c.moving(now - timedelta(minutes=m)) for m in range(2, 11))
    if ended_recently and hr_pct is not None and hr_pct > 5:
        return result('recovering', 0.75, ['You were active in the last 10 minutes and your heart rate is coming down.'])

    # 4. The patient said they're not okay, or reported panic.
    if _latest_event(events, 'not_okay', now - NOT_OKAY_WINDOW):
        return result('distressed', 0.85, ["You told us you're not okay."])
    panic = _latest_event(events, 'self_report', now - NOT_OKAY_WINDOW, ('panic',))
    if panic:
        return result('distressed', 0.85, ['You reported feeling panicky.'])

    # 5. Stress: HR up + HRV down + sitting still.
    if c.stressed_at(now):
        reasons = [f'HR {hr_pct}% above your resting rate while sitting still.',
                   f'Heart-rate variability {hrv_pct}% below your usual.']
        sustained = all(c.stressed_at(now - timedelta(minutes=m)) for m in (5, 10))
        worse = hr_pct >= WORSE_HR_PCT and hrv_pct >= WORSE_HRV_PCT
        if sustained or worse:
            reasons.append('This has lasted 10+ minutes.' if sustained else 'The signs are getting stronger.')
            return result('distressed', 0.85, reasons)
        return result('stressed', 0.75, reasons)

    # 6. Elevated but not enough to alert.
    if c.low_movement(now) and ((hr_pct or 0) >= ELEVATED_HR_PCT or (hrv_pct or 0) >= ELEVATED_HRV_PCT):
        bits = []
        if (hr_pct or 0) >= ELEVATED_HR_PCT:
            bits.append(f'HR {hr_pct}% above resting')
        if (hrv_pct or 0) >= ELEVATED_HRV_PCT:
            bits.append(f'HRV {hrv_pct}% below usual')
        return result('elevated', 0.6, [', '.join(bits) + ' - keeping an eye on it.'])

    return result('calm', 0.8, ['Heart rate and variability are near your usual levels.'])


def _explain(state, kind):
    return {
        'calm': 'Your body looks settled right now.',
        'elevated': "Your body is a little more activated than usual. Nothing to worry about, we're keeping an eye on it.",
        'exercising': "You're moving, so a higher heart rate is expected. No stress alert.",
        'recovering': 'Your body is cooling down after activity.',
        'stressed': 'Your body seems tense. A two-minute breathing exercise could help.',
        'distressed': "You've seemed tense for a while. Let's work through it together, one step at a time.",
        'emergency': ('Possible fall detected. If you are hurt, call 911 now.' if kind == 'fall' else
                      'These can be warning signs of a medical emergency. Call 911 now.'),
    }[state]
