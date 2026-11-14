"""Test setup: in-memory SQLite, a throwaway encryption key, DEMO_MODE + DEV_LOGIN on.

Run from the repo root:  pytest backend/wearable/tests
"""
import os
import sys

import pytest
from cryptography.fernet import Fernet

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND)

# Set explicitly so a developer's backend/.env can't change test behaviour (load_dotenv never overrides).
os.environ.update({
    'DATABASE_URL': 'sqlite://',
    'WEARABLE_DATA_KEY': Fernet.generate_key().decode(),
    'DEMO_MODE': '1',
    'DEV_LOGIN': '1',
    'AI_DATA_TIER': 'free',
    'WEARABLE_REQUIRE_HTTPS': 'allow_localhost',
    'WEARABLE_SECURE_COOKIES': '0',
    'WEARABLE_IDLE_MINUTES': '15',
    'WEARABLE_RATE_LIMIT': '60',
    'NTFY_TOPIC': '',
    'FLASK_SECRET_KEY': 'test-secret',
    'GOOGLE_CLIENT_ID': '',
    'GOOGLE_CLIENT_SECRET': '',
})

from app import app as flask_app  # noqa: E402
from models import User, db  # noqa: E402
from wearable import security  # noqa: E402


@pytest.fixture()
def app():
    flask_app.config.update(TESTING=True)
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        security.ingest_limiter.reset()
        yield flask_app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


def login_as(client, role):
    """Use the DEV_LOGIN helper: role is patient | family | provider."""
    r = client.get(f'/wearable/dev-login/{role}')
    assert r.status_code == 302, r.data
    return User.query.filter_by(google_sub=f'dev-demo-{role}').first()


@pytest.fixture()
def patient_client(app):
    c = app.test_client()
    user = login_as(c, 'patient')
    assert c.post('/api/wearable/consent', json={'accept': True}).status_code == 200
    c.patient = user
    return c


@pytest.fixture()
def device_token(patient_client):
    r = patient_client.post('/api/wearable/devices', json={'label': 'Test watch'})
    assert r.status_code == 201
    return r.json['token']


@pytest.fixture()
def family_client(app, patient_client):
    c = app.test_client()
    c.user = login_as(c, 'family')
    return c


@pytest.fixture()
def provider_client(app, patient_client):
    c = app.test_client()
    c.user = login_as(c, 'provider')
    return c
