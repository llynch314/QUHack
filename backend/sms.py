"""Text-message (SMS) alerts to family members, sent with Twilio.

Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER in backend/.env.
Without them, texts are printed in the `make run` terminal instead (demo mode), so
the whole flow still works for a demo without a Twilio account.

Texts never include chat text or the patient's note: only who needs support, the
kind of alert, and a link to the Alerts page. Replying STOP is handled by Twilio.
"""
import logging
import os
import re
import secrets
import threading
from datetime import timedelta

from werkzeug.security import check_password_hash, generate_password_hash

log = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
RESEND_WAIT = timedelta(seconds=60)


def _setting(name):
    return (os.getenv(name) or '').strip()


def twilio_configured():
    return all(_setting(n) for n in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_FROM_NUMBER'))


def normalize_phone(raw):
    """Return the number in E.164 form (+15551234567), or None if it doesn't look valid.

    10-digit numbers are treated as US/Canada; other countries need a leading +.
    """
    raw = (raw or '').strip()
    digits = re.sub(r'\D', '', raw)
    if raw.startswith('+'):
        return f'+{digits}' if 8 <= len(digits) <= 15 else None
    if len(digits) == 10:
        return f'+1{digits}'
    if len(digits) == 11 and digits.startswith('1'):
        return f'+{digits}'
    return None


def new_code():
    """A random 6-digit code and its hash (only the hash is stored)."""
    code = f'{secrets.randbelow(1_000_000):06d}'
    return code, generate_password_hash(code)


def code_matches(code_hash, code):
    return check_password_hash(code_hash, (code or '').strip())


def send_sms(to, body):
    """Send one text now. Raises on a Twilio error so callers can report it."""
    if not twilio_configured():
        log.warning('SMS (demo mode, not sent - add Twilio keys to .env) to %s: %s', to, body)
        return 'demo'
    from twilio.rest import Client   # imported here so the app runs without twilio installed
    client = Client(_setting('TWILIO_ACCOUNT_SID'), _setting('TWILIO_AUTH_TOKEN'))
    message = client.messages.create(to=to, from_=_setting('TWILIO_FROM_NUMBER'), body=body)
    log.info('SMS sent to %s (%s)', to, message.sid)
    return message.sid


def _send_all(messages):
    for to, body in messages:
        try:
            send_sms(to, body)
        except Exception:
            log.exception('Could not text %s', to)


def dispatch(messages):
    """Send texts in the background so the chat reply isn't held up waiting for Twilio."""
    if messages:
        threading.Thread(target=_send_all, args=(messages,), daemon=True).start()


def alert_text(patient_name, label, alerts_url):
    return (f'AttuneMIND alert: {patient_name} may need support ({label}). '
            f'See your Alerts page: {alerts_url} . '
            f'If they might be in danger, call or text 988, or call 911.')
