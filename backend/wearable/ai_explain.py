"""Optional friendly explanation from Gemini (PRD §5A.4).

- Off automatically when AI_DATA_TIER=free (Google may train on free-tier data).
- Off when the patient switched AI explanations off.
- Never for emergencies: the Call 911 text is always the fixed, rule-based one.
- Sends ONLY derived, de-identified numbers. No name, email, IDs, timestamps or raw vitals.
- Every call is logged in AIUsageLog as metadata (feature, model, tier, field names), never content.
"""
import logging
import os

from models import db

from .models import AIUsageLog
from .security import ai_allowed_for_wearable, ai_tier

log = logging.getLogger('mindconnect.wearable')

FIELDS = ('state', 'hr_pct_above_rest', 'hrv_pct_below', 'movement')
_client_factory = None   # tests can inject a fake client


def _get_client():
    if _client_factory is not None:
        return _client_factory()
    from gemini_client import get_client   # main's shared Gemini client (google-genai)
    return get_client()


def derived_payload(reading):
    m = reading.get('metrics') or {}
    return {'state': reading['state'], 'hr_pct_above_rest': m.get('hr_pct_above_rest'),
            'hrv_pct_below': m.get('hrv_pct_below'), 'movement': m.get('movement')}


def maybe_explain(patient_id, reading, profile):
    fallback = reading['explanation']
    if not ai_allowed_for_wearable() or not profile.ai_explanations or reading['tier'] not in (1, 2):
        return fallback
    model = os.getenv('GEMINI_CHAT_MODEL', 'gemini-3.8-flash')
    data = derived_payload(reading)
    prompt = ('You are a gentle wellbeing companion. In ONE short, warm sentence (max 25 words), explain to the user '
              'what these body signals suggest and invite them to take a 2-minute calming break. Do not diagnose, '
              f'do not mention numbers you were not given. Signals: {data}')
    try:
        resp = _get_client().models.generate_content(model=model, contents=prompt)
        text = (getattr(resp, 'text', '') or '').strip()
    except Exception:
        log.warning('wearable: AI explanation failed, using rule-based text (patient=%s)', patient_id)
        text = ''
    db.session.add(AIUsageLog(patient_id=patient_id, feature='wearable_explanation', model=model,
                              tier=ai_tier(), fields_sent=','.join(FIELDS)))
    db.session.commit()
    return text[:300] if text else fallback
