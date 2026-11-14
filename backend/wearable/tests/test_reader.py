"""Unit tests for every row of PRD §7.1, especially exercise vs. stress."""
from datetime import datetime, timedelta, timezone

from wearable import reader, simulator

NOW = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
BASE = {'resting_hr': 65, 'hrv': 45}


def _from_payload(payload):
    samples = [{**s, 'ts': datetime.fromisoformat(s['ts'].replace('Z', '+00:00'))} for s in payload['samples']]
    events = [{**e, 'ts': datetime.fromisoformat(e['ts'].replace('Z', '+00:00'))} for e in payload['events']]
    return samples, events


def run(scenario, extra_events=()):
    samples, events = _from_payload(simulator.generate(scenario, now=NOW))
    return reader.classify(samples, events + list(extra_events), BASE, NOW)


def series(minutes, **values):
    """Constant values per minute for the last `minutes` minutes."""
    out = []
    for i in range(minutes):
        ts = NOW - timedelta(minutes=minutes - 1 - i)
        for typ, v in values.items():
            out.append({'type': typ, 'value': v(i) if callable(v) else v, 'ts': ts})
    return out


def test_baseline_is_calm():
    r = run('baseline')
    assert r['state'] == 'calm' and r['tier'] == 0


def test_exercise_is_not_stress():
    r = run('exercise')
    assert r['state'] == 'exercising'
    assert r['tier'] == 0   # no alert even though HR is high and HRV is low


def test_high_hr_low_hrv_with_steps_is_exercise_not_stress():
    s = series(8, heart_rate=130, hrv_sdnn=20, steps=110, active_energy=1, workout_active=0)
    assert reader.classify(s, [], BASE, NOW)['state'] == 'exercising'


def test_active_energy_alone_counts_as_exercise():
    s = series(8, heart_rate=120, hrv_sdnn=22, steps=5, active_energy=8, workout_active=0)
    assert reader.classify(s, [], BASE, NOW)['state'] == 'exercising'


def test_recovering_after_exercise():
    # 10 min of exercise that ended 4 minutes ago, HR still coming down
    s = series(14, heart_rate=lambda i: 140 if i < 10 else 110 - 5 * (i - 10),
               hrv_sdnn=30, steps=lambda i: 130 if i < 10 else 2,
               active_energy=lambda i: 10 if i < 10 else 0.5, workout_active=lambda i: 1 if i < 10 else 0)
    r = reader.classify(s, [], BASE, NOW)
    assert r['state'] == 'recovering' and r['tier'] == 0


def test_stress_spike_is_stressed_tier1():
    r = run('stress_spike')
    assert r['state'] == 'stressed' and r['tier'] == 1
    assert any('above your resting rate while sitting still' in x for x in r['reasons'])


def test_stress_needs_low_hrv_too():
    s = series(8, heart_rate=92, hrv_sdnn=44, steps=2, active_energy=0.5, workout_active=0)
    assert reader.classify(s, [], BASE, NOW)['state'] == 'elevated'


def test_sustained_distress_is_tier2():
    r = run('sustained_distress')
    assert r['state'] == 'distressed' and r['tier'] == 2


def test_fall_is_emergency():
    r = run('fall')
    assert r['state'] == 'emergency' and r['kind'] == 'fall' and r['tier'] == 3
    assert '911' in r['explanation']


def test_im_ok_clears_fall():
    samples, events = _from_payload(simulator.generate('fall', now=NOW))
    events.append({'type': 'im_ok', 'ts': NOW + timedelta(seconds=10)})
    r = reader.classify(samples, events, BASE, NOW + timedelta(seconds=20))
    assert r['state'] != 'emergency'


def test_chest_pain_self_report_is_cardiac_warning():
    s = series(6, heart_rate=70, hrv_sdnn=45, steps=0, active_energy=0.5, workout_active=0)
    ev = [{'type': 'self_report', 'ts': NOW, 'meta': {'symptom': 'chest_pain'}}]
    r = reader.classify(s, ev, BASE, NOW)
    assert r['state'] == 'emergency' and r['kind'] == 'cardiac_warning'


def test_cardiac_warning_scenario():
    r = run('cardiac_warning')
    assert r['state'] == 'emergency' and r['kind'] == 'cardiac_warning'


def test_hr_over_150_at_rest_is_cardiac_warning():
    s = series(6, heart_rate=158, hrv_sdnn=20, steps=0, active_energy=0.3, workout_active=0)
    r = reader.classify(s, [], BASE, NOW)
    assert r['state'] == 'emergency' and r['kind'] == 'cardiac_warning'


def test_hr_over_150_while_working_out_is_exercise():
    s = series(6, heart_rate=165, hrv_sdnn=15, steps=160, active_energy=12, workout_active=1)
    assert reader.classify(s, [], BASE, NOW)['state'] == 'exercising'


def test_hr_below_40_is_cardiac_warning():
    s = series(6, heart_rate=36, hrv_sdnn=45, steps=0, active_energy=0.3, workout_active=0)
    assert reader.classify(s, [], BASE, NOW)['kind'] == 'cardiac_warning'


def test_im_exercising_correction_holds_off_stress_for_20_min():
    samples, events = _from_payload(simulator.generate('stress_spike', now=NOW))
    ev = events + [{'type': 'exercising', 'ts': NOW - timedelta(minutes=15)}]
    assert reader.classify(samples, ev, BASE, NOW)['state'] == 'exercising'
    ev = events + [{'type': 'exercising', 'ts': NOW - timedelta(minutes=25)}]
    assert reader.classify(samples, ev, BASE, NOW)['state'] == 'stressed'


def test_not_okay_correction_is_distressed():
    r = run('baseline', [{'type': 'not_okay', 'ts': NOW - timedelta(minutes=1)}])
    assert r['state'] == 'distressed'


def test_no_data_is_low_confidence_calm():
    r = reader.classify([], [], BASE, NOW)
    assert r['state'] == 'calm' and r['confidence'] < 0.5


def test_metrics_are_derived_only():
    r = run('stress_spike')
    assert set(r['metrics']) == {'hr', 'hrv', 'resting_hr', 'hr_pct_above_rest', 'hrv_pct_below', 'movement'}


def test_simulator_is_deterministic():
    assert simulator.generate('exercise', now=NOW) == simulator.generate('exercise', now=NOW)
