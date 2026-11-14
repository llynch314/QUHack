"""HIPAA technical safeguards for the wearable module (PRD §5A).

- Field encryption at rest (Fernet = AES-128-CBC + HMAC-SHA256) via the EncryptedText column type.
- Device tokens: random 32 bytes, shown once, only the SHA-256 hash is stored.
- HTTPS enforcement for wearable routes (tunnel sets X-Forwarded-Proto).
- Audit log helper (append-only) and a small in-memory rate limiter.

Never log vitals values or notes from this module: IDs and event types only.
"""
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from flask import g, jsonify, request, session
from sqlalchemy.types import Text, TypeDecorator

log = logging.getLogger('mindconnect.wearable')

LOOPBACK = {'127.0.0.1', '::1', 'localhost'}


def utcnow():
    return datetime.now(timezone.utc)


def as_utc(dt):
    """SQLite drops tzinfo; treat naive datetimes as UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def demo_mode():
    return os.getenv('DEMO_MODE') == '1'


# ---------- Encryption at rest ----------

_fernet = None
_fernet_lock = threading.Lock()
KEY_SOURCE = 'unset'   # 'env' or 'dev-generated' (shown in the privacy panel)


def get_fernet():
    global _fernet, KEY_SOURCE
    if _fernet is not None:
        return _fernet
    with _fernet_lock:
        if _fernet is not None:
            return _fernet
        key = (os.getenv('WEARABLE_DATA_KEY') or '').strip()
        if key:
            KEY_SOURCE = 'env'
        elif demo_mode():
            # Persist the dev key next to the DB so data survives restarts in demo mode.
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'instance', 'wearable_dev.key')
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    key = f.read().decode().strip()
            else:
                key = Fernet.generate_key().decode()
                with open(path, 'wb') as f:
                    f.write(key.encode())
            KEY_SOURCE = 'dev-generated'
            log.warning('!!! WEARABLE_DATA_KEY is not set. DEMO_MODE=1, so a DEV key was generated at '
                        'backend/instance/wearable_dev.key. Never use this with real patient data. !!!')
        else:
            raise RuntimeError('WEARABLE_DATA_KEY is not set in backend/.env. Generate one with: '
                               'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"')
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet


def reset_crypto_for_tests():
    global _fernet, KEY_SOURCE
    _fernet, KEY_SOURCE = None, 'unset'


def encrypt_value(value):
    if value is None:
        return None
    return get_fernet().encrypt(json.dumps(value).encode()).decode()


def decrypt_value(token):
    if token is None:
        return None
    try:
        return json.loads(get_fernet().decrypt(token.encode()))
    except InvalidToken:
        # Tampered or wrong key: integrity check failed. Never return a guess.
        log.error('wearable: encrypted field failed integrity check')
        raise


class EncryptedText(TypeDecorator):
    """Stores any JSON-serialisable value as Fernet ciphertext. Transparent to the ORM."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_value(value)

    def process_result_value(self, value, dialect):
        return decrypt_value(value)


# ---------- Device tokens ----------

def new_device_token():
    """Return (plaintext token, sha256 hex). The plaintext is shown once and never stored."""
    token = secrets.token_urlsafe(32)   # 32 random bytes
    return token, hash_token(token)


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_match(a, b):
    return hmac.compare_digest(a, b)


# ---------- HTTPS / transport ----------

def https_mode():
    """strict: HTTPS always required. allow_localhost (default): plain HTTP only from this machine,
    so you can test at http://127.0.0.1:5050. Everything else (LAN, tunnel over http) is rejected."""
    return os.getenv('WEARABLE_REQUIRE_HTTPS', 'allow_localhost')


def request_is_secure():
    if request.is_secure:
        return True
    proto = request.headers.get('X-Forwarded-Proto', '').split(',')[0].strip().lower()
    # Only trust the forwarded header from a local proxy (cloudflared / ngrok run on this laptop).
    return proto == 'https' and request.remote_addr in LOOPBACK


def transport_allowed():
    if request_is_secure():
        return True
    if https_mode() == 'strict':
        return False
    forwarded = request.headers.get('X-Forwarded-Proto')
    return request.remote_addr in LOOPBACK and forwarded is None


def https_rejection():
    return jsonify(error='HTTPS is required for wearable data. Use the encrypted tunnel URL.'), 403


# ---------- Rate limiting ----------

class RateLimiter:
    def __init__(self, limit, window_s=60):
        self.limit, self.window = limit, window_s
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key):
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self):
        with self.lock:
            self.hits.clear()


ingest_limiter = RateLimiter(int(os.getenv('WEARABLE_RATE_LIMIT', '60')))
MAX_INGEST_BYTES = 256 * 1024
MAX_SAMPLES = 1000


# ---------- Idle logoff ----------

def idle_minutes():
    return float(os.getenv('WEARABLE_IDLE_MINUTES', '15'))


def check_idle():
    """Returns True if the session expired from inactivity (and clears it).
    Background polls send X-Wearable-Poll: 1 and don't count as activity unless the
    page also says the user was active (X-User-Active: 1)."""
    if g.get('user') is None:
        return False
    now = time.time()
    last = session.get('wearable_active_at')
    if last and now - last > idle_minutes() * 60:
        session.clear()
        g.user = None
        return True
    is_poll = request.headers.get('X-Wearable-Poll') == '1'
    if not is_poll or request.headers.get('X-User-Active') == '1' or not last:
        session['wearable_active_at'] = now
    return False


# ---------- Audit log ----------

AUDIT_COALESCE = timedelta(seconds=60)


def audit(action, patient_id, outcome='allowed', resource=None, actor_id=None, actor_role=None):
    """Append an audit row. Identical allowed reads by the same actor within 60 s are
    coalesced so 5-second polling doesn't flood the log; writes and denials always log."""
    from models import db
    from .models import AuditLog
    from . import integrations

    user = g.get('user')
    if actor_id is None and user is not None:
        actor_id = user.id
    if actor_role is None:
        actor_role = integrations.get_role(user) if user is not None else 'anonymous'
    if outcome == 'allowed' and action.startswith('read'):
        recent = (AuditLog.query
                  .filter_by(actor_id=actor_id, actor_role=actor_role, action=action,
                             patient_id=patient_id, outcome=outcome)
                  .order_by(AuditLog.id.desc()).first())
        if recent and utcnow() - as_utc(recent.ts) < AUDIT_COALESCE:
            return recent
    row = AuditLog(actor_id=actor_id, actor_role=actor_role, action=action, resource=resource,
                   patient_id=patient_id, ip=request.remote_addr if request else None,
                   outcome=outcome)
    db.session.add(row)
    db.session.commit()
    log.info('wearable audit: action=%s patient=%s actor=%s role=%s outcome=%s',
             action, patient_id, actor_id, actor_role, outcome)
    return row


# ---------- AI data tier (PRD §5A.4) ----------

def ai_tier():
    tier = os.getenv('AI_DATA_TIER', 'free').strip().lower()
    return tier if tier in ('free', 'paid', 'vertex_baa') else 'free'


def ai_allowed_for_wearable():
    return ai_tier() in ('paid', 'vertex_baa')
