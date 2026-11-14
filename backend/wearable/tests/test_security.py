"""Encryption at rest, AI data-tier rules and no-PHI-in-logs (PRD §5A.2, §5A.4, §5A.6)."""
import logging
import re

import pytest
from cryptography.fernet import InvalidToken
from sqlalchemy import text

from models import db
from wearable import ai_explain, security, simulator
from wearable.models import AIUsageLog


def test_db_columns_are_ciphertext(patient_client):
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'fall'})
    patient_client.post('/api/wearable/self-report', json={'symptom': 'chest_pain'})   # event with meta
    patient_client.post(f'/api/patients/{patient_client.patient.id}/wearable-report')
    for table, col in (('wearable_vital_sample', 'value_enc'), ('wearable_event', 'meta_enc'),
                       ('wearable_state_reading', 'reasons_enc')):
        raw = [r[0] for r in db.session.execute(text(f'SELECT {col} FROM {table} WHERE {col} IS NOT NULL'))]
        assert raw, table
        for v in raw:
            assert v.startswith('gAAAA'), (table, v[:20])   # Fernet token
            assert 'heart' not in v and 'fall' not in v


def test_tampered_ciphertext_fails_integrity(patient_client):
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'baseline'})
    raw = db.session.execute(text('SELECT id, value_enc FROM wearable_vital_sample LIMIT 1')).first()
    tampered = raw[1][:-6] + ('AAAAAA' if not raw[1].endswith('AAAAAA') else 'BBBBBB')
    with pytest.raises(InvalidToken):
        security.decrypt_value(tampered)


def test_missing_key_still_starts_with_a_local_key(monkeypatch):
    """A teammate's older .env has no WEARABLE_DATA_KEY: the app must still start (data still encrypted)."""
    monkeypatch.delenv('WEARABLE_DATA_KEY', raising=False)
    monkeypatch.setenv('DEMO_MODE', '0')
    security.reset_crypto_for_tests()
    try:
        f = security.get_fernet()
        assert security.KEY_SOURCE == 'dev-generated'
        assert f.decrypt(f.encrypt(b'72')) == b'72'
    finally:
        monkeypatch.undo()
        security.reset_crypto_for_tests()
        security.get_fernet()


class FakeClient:
    def __init__(self):
        self.calls = []
        outer = self

        class Messages:
            def create(self, model, max_tokens, messages):
                outer.calls.append(messages[0]['content'])
                block = type('B', (), {'type': 'text', 'text': 'Your body seems a bit tense; a short breathing break could help.'})()
                return type('R', (), {'content': [block]})()
        self.messages = Messages()


def test_free_tier_never_calls_ai(patient_client, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(ai_explain, '_client_factory', lambda: fake)
    monkeypatch.setenv('AI_DATA_TIER', 'free')
    for s in simulator.SCENARIOS:
        patient_client.post('/api/wearable/demo/scenario', json={'scenario': s})
    assert fake.calls == []
    assert AIUsageLog.query.count() == 0


def test_paid_tier_sends_only_derived_fields(patient_client, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(ai_explain, '_client_factory', lambda: fake)
    monkeypatch.setenv('AI_DATA_TIER', 'paid')
    r = patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'stress_spike'}).json
    assert len(fake.calls) == 1
    prompt = fake.calls[0]
    assert 'Demo Patient' not in prompt and 'example.com' not in prompt and '2026-' not in prompt
    assert 'hr_pct_above_rest' in prompt and "'hr':" not in prompt
    assert r['state']['explanation'].startswith('Your body seems a bit tense')
    log = AIUsageLog.query.one()
    assert log.tier == 'paid' and log.fields_sent == 'state,hr_pct_above_rest,hrv_pct_below,movement'


def test_patient_can_switch_ai_off(patient_client, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(ai_explain, '_client_factory', lambda: fake)
    monkeypatch.setenv('AI_DATA_TIER', 'paid')
    patient_client.post('/api/wearable/profile', json={'ai_explanations': False})
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'stress_spike'})
    assert fake.calls == []


def test_emergency_never_uses_ai(patient_client, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(ai_explain, '_client_factory', lambda: fake)
    monkeypatch.setenv('AI_DATA_TIER', 'paid')
    r = patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'cardiac_warning'}).json
    assert fake.calls == [] and '911' in r['state']['explanation']


def test_no_vitals_in_logs_during_full_simulator_run(patient_client, caplog):
    caplog.set_level(logging.DEBUG)
    values = set()
    for s in simulator.SCENARIOS:
        values |= {str(round(x['value'], 1)) for x in simulator.generate(s)['samples'] if x['value'] >= 30}
        patient_client.post('/api/wearable/demo/scenario', json={'scenario': s})
    patient_client.post('/api/wearable/feedback', json={'correction': 'im_ok'})
    logs = '\n'.join(r.getMessage() for r in caplog.records)
    assert 'wearable' in logs   # we did log something
    leaked = [v for v in values if re.search(rf'(?<![\d.]){re.escape(v)}(?![\d])', logs)]
    assert leaked == []
    for word in ('heart_rate', 'hrv', 'chest_pain', 'Demo Patient'):
        assert word not in logs
