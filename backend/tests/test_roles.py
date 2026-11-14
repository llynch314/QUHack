"""Checks that each account type sees exactly what it should.  Run: pytest  (from backend/)"""
import os
import sys
from pathlib import Path

import pytest

os.environ['DATABASE_URL'] = 'sqlite://'           # in-memory database for tests
os.environ['FLASK_SECRET_KEY'] = 'test'
os.environ['DEV_LOGIN'] = '1'
os.environ.pop('GOOGLE_CLIENT_ID', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module  # noqa: E402
from models import Alert, User, _now, db  # noqa: E402

flask_app = app_module.app
flask_app.config['TESTING'] = True


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    monkeypatch.setattr(app_module, 'chat_reply',
                        lambda history, emotion=None: {'reply': 'bot reply', 'crisis': False})
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
    yield


def make_user(role, name):
    with flask_app.app_context():
        u = User(google_sub=f'sub-{name}', role=role, name=name.title(), email=f'{name}@example.com',
                 terms_accepted_at=_now())
        db.session.add(u)
        db.session.commit()
        return u.id


def client_for(user_id):
    c = flask_app.test_client()
    with c.session_transaction() as s:
        s['user_id'] = user_id
    return c


@pytest.fixture
def world():
    """A patient with a linked provider and family member, plus unlinked outsiders."""
    ids = {name: make_user(role, name) for role, name in [
        ('patient', 'pat'), ('provider', 'doc'), ('family', 'mom'),
        ('provider', 'otherdoc'), ('family', 'stranger'), ('patient', 'otherpat')]}
    c = {name: client_for(uid) for name, uid in ids.items()}
    for email in ('doc@example.com', 'mom@example.com'):
        assert c['pat'].post('/api/care-team', json={'email': email}).status_code == 201
    return ids, c


# ---------- sign-in doors ----------

def test_dev_login_consent_then_role_home():
    """New demo family account: consent screen first, then the family Alerts page."""
    c = flask_app.test_client()
    r = c.get(c.get('/login?role=family').headers['Location'])     # /login -> /login/dev
    assert r.headers['Location'].endswith('/welcome')
    page = c.get('/welcome').data
    assert b'family member account' in page and b'save_expressions' not in page
    assert c.get('/api/alerts').status_code == 403                  # blocked until they agree
    r = c.post('/welcome', data={'agree': 'yes'})
    assert r.headers['Location'].endswith('/family')
    assert c.get('/api/alerts').status_code == 200


def test_patient_consent_shows_expression_option():
    c = flask_app.test_client()
    c.get(c.get('/login?role=patient').headers['Location'])
    assert b'save_expressions' in c.get('/welcome').data


def test_role_mismatch_is_refused(monkeypatch):
    uid = make_user('family', 'mom')
    c = flask_app.test_client()
    with flask_app.app_context():
        from auth import _finish_sign_in
        with flask_app.test_request_context():
            r = _finish_sign_in(db.session.get(User, uid), 'patient', '/')
            assert '/signin' in r.headers['Location']


def test_pages_by_role(world):
    ids, c = world
    assert c['pat'].get('/care-team').status_code == 200
    assert c['pat'].get('/report').status_code == 200
    assert c['doc'].get('/provider').status_code == 200
    assert c['doc'].get(f"/provider/patients/{ids['pat']}").status_code == 200
    assert c['mom'].get('/family').status_code == 200
    # Wrong role gets redirected away
    assert c['mom'].get('/report').status_code == 302
    assert c['doc'].get('/care-team').status_code == 302
    assert c['otherdoc'].get(f"/provider/patients/{ids['pat']}").status_code == 403


# ---------- documents: patient + linked provider only ----------

def test_documents_access(world):
    ids, c = world
    url = f"/api/patients/{ids['pat']}/documents"
    assert c['pat'].post(url, json={'title': 'Medication list'}).status_code == 201
    r = c['doc'].post(url, json={'title': 'Session notes', 'body': '...'})
    assert r.status_code == 201
    doc_id = r.json['document']['id']
    assert len(c['pat'].get(url).json['documents']) == 2
    assert len(c['doc'].get(url).json['documents']) == 2
    for who in ('mom', 'otherdoc', 'stranger', 'otherpat'):
        assert c[who].get(url).status_code == 403, who
        assert c[who].get(f'/api/documents/{doc_id}').status_code == 403, who


def test_provider_deletes_only_own_documents(world):
    ids, c = world
    url = f"/api/patients/{ids['pat']}/documents"
    mine = c['pat'].post(url, json={'title': "Patient's"}).json['document']['id']
    theirs = c['doc'].post(url, json={'title': "Doctor's"}).json['document']['id']
    assert c['doc'].delete(f'/api/documents/{mine}').status_code == 403
    assert c['doc'].delete(f'/api/documents/{theirs}').status_code == 204


def test_progress_report_shared_as_document(world):
    ids, c = world
    assert c['pat'].post('/api/documents/progress-report').status_code == 400   # no check-ins yet
    c['pat'].post('/api/checkins', json={'activity': 'breathing', 'stress_before': 8, 'stress_after': 4})
    assert c['pat'].post('/api/documents/progress-report').status_code == 201
    docs = c['doc'].get(f"/api/patients/{ids['pat']}/documents").json['documents']
    assert docs[0]['category'] == 'progress-report' and '-4.0' in docs[0]['body']


def test_checkins_patient_only(world):
    ids, c = world
    for who in ('doc', 'mom'):
        assert c[who].get('/api/checkins').status_code == 403


# ---------- alerts: patient + linked family only ----------

def test_alerts_access(world):
    ids, c = world
    r = c['pat'].post('/api/alerts/sos', json={'kind': 'panic_attack'})
    assert r.status_code == 201 and r.json['family_notified'] == 1
    alert_id = r.json['alert']['id']
    assert len(c['mom'].get('/api/alerts').json['alerts']) == 1
    assert c['stranger'].get('/api/alerts').json['alerts'] == []
    assert c['doc'].get('/api/alerts').status_code == 403
    ack = c['mom'].post(f'/api/alerts/{alert_id}/acknowledge')
    assert ack.json['alert']['acknowledged_by'] == 'Mom'
    assert c['stranger'].post(f'/api/alerts/{alert_id}/acknowledge').status_code == 403
    assert c['mom'].post('/api/alerts/sos', json={}).status_code == 403


# ---------- chat alerts ----------

def chat(client, text):
    return client.post('/api/chat', json={'messages': [{'role': 'user', 'text': text}]})


def test_panic_in_chat_alerts_family_without_leaking_text(world):
    ids, c = world
    r = chat(c['pat'], "I'm having a panic attack and can't breathe")
    assert r.json['alert_sent'] is True
    alerts = c['mom'].get('/api/alerts').json['alerts']
    assert alerts[0]['kind'] == 'panic_attack' and 'breathe' not in alerts[0]['note']
    # Same kind again right away doesn't spam family
    assert chat(c['pat'], 'still panicking').json['alert_sent'] is False


def test_crisis_from_model_flag(world, monkeypatch):
    ids, c = world
    monkeypatch.setattr(app_module, 'chat_reply', lambda h, e=None: {'reply': 'x', 'crisis': True})
    assert chat(c['pat'], 'I want to die').json['alert_sent'] is True
    assert c['mom'].get('/api/alerts').json['alerts'][0]['kind'] == 'crisis'


def test_auto_alerts_off_and_anonymous_chat(world):
    ids, c = world
    c['pat'].patch('/api/me/settings', json={'auto_alerts': False})
    assert chat(c['pat'], 'total meltdown').json['alert_sent'] is False
    assert chat(flask_app.test_client(), 'total meltdown').json['alert_sent'] is False
    assert chat(c['mom'], 'total meltdown').json['alert_sent'] is False   # family chatting
    with flask_app.app_context():
        assert Alert.query.count() == 0


# ---------- care team ----------

def test_removing_member_revokes_access(world):
    ids, c = world
    links = c['pat'].get('/api/care-team').json['links']
    doc_link = next(l for l in links if l['member']['role'] == 'provider')
    assert c['pat'].delete(f"/api/care-team/{doc_link['id']}").status_code == 204
    assert c['doc'].get(f"/api/patients/{ids['pat']}/documents").status_code == 403


def test_care_team_rules(world):
    ids, c = world
    assert c['mom'].post('/api/care-team', json={'email': 'otherdoc@example.com'}).status_code == 403
    assert c['pat'].post('/api/care-team', json={'email': 'otherpat@example.com'}).status_code == 400
    assert c['pat'].post('/api/care-team', json={'email': 'DOC@example.com'}).status_code == 409
    links = c['doc'].get('/api/care-team').json['links']
    assert [l['patient']['id'] for l in links] == [ids['pat']]
    assert c['otherpat'].delete(f"/api/care-team/{links[0]['id']}").status_code == 404


def test_delete_account_cleans_up(world):
    ids, c = world
    c['pat'].post('/api/alerts/sos', json={'kind': 'meltdown'})
    assert c['pat'].post('/api/me/delete').status_code == 200
    assert c['mom'].get('/api/alerts').json['alerts'] == []
    assert c['doc'].get('/api/care-team').json['links'] == []
