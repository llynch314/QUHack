"""Optional friendly explanation from Claude, through main's shared client (claude_client.py) (PRD §5A.4).

- Off automatically when AI_DATA_TIER=free (the default): wearable data stays on our server until
  the team confirms its AI account terms (paid / BAA) cover health data.
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
    from claude_client import get_client   # main's shared Claude client (ANTHROPIC_API_KEY)
    return get_client()


def derived_payload(reading):
    m = reading.get('metrics') or {}
    return {'state': reading['state'], 'hr_pct_above_rest': m.get('hr_pct_above_rest'),
            'hrv_pct_below': m.get('hrv_pct_below'), 'movement': m.get('movement')}


def maybe_explain(patient_id, reading, profile):
    fallback = reading['explanation']
    if not ai_allowed_for_wearable() or not profile.ai_explanations or reading['tier'] not in (1, 2):
        return fallback
    model = os.getenv('CLAUDE_CHAT_MODEL', 'claude-opus-5-5')
    data = derived_payload(reading)
    prompt = ('You are a gentle wellbeing companion. In ONE short, warm sentence (max 25 words), explain to the user '
              'what these body signals suggest and invite them to take a 2-minute calming break. Do not diagnose, '
              f'do not mention numbers you were not given. Signals: {data}')
    try:
        resp = _get_client().messages.create(model=model, max_tokens=120,
                                             messages=[{'role': 'user', 'content': prompt}])
        text = ''.join(getattr(b, 'text', '') for b in resp.content if getattr(b, 'type', '') == 'text').strip()
    except Exception:
        log.warning('wearable: AI explanation failed, using rule-based text (patient=%s)', patient_id)
        text = ''
    db.session.add(AIUsageLog(patient_id=patient_id, feature='wearable_explanation', model=model,
                              tier=ai_tier(), fields_sent=','.join(FIELDS)))
    db.session.commit()
    return text[:300] if text else fallback
