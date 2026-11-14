"""Checks that each account type sees exactly what it should.  Run: pytest  (from backend/)"""
import os
import sys
from pathlib import Path

import pytest

os.environ['DATABASE_URL'] = 'sqlite://'           # in-memory database for tests
os.environ['FLASK_SECRET_KEY'] = 'test'
os.environ['DEV_LOGIN'] = '1'
os.environ['GOOGLE_CLIENT_ID'] = ''          # empty (not removed) so load_dotenv() in app.py can't refill it from .env
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module  # noqa: E402
from models import Alert, User, _now, db  # noqa: E402
from organizations import organization_for_email  # noqa: E402

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
        if role == 'provider' and name != 'newdoc':
            u.organization, u.specialty = 'City Hospital', 'Psychiatrist'
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
    # Old patient pages now open tabs in the patient app (frontend/test.html)
    assert c['pat'].get('/care-team').headers['Location'].endswith('/test#care-team')
    assert c['pat'].get('/report').headers['Location'].endswith('/test#mood-history')
    assert c['pat'].get('/account').headers['Location'].endswith('/test#settings')
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


# ---------- account page + provider profile ----------

def test_account_page_for_every_role(world):
    ids, c = world
    for who in ('doc', 'mom'):                     # patients use the app's Settings tab instead
        page = c[who].get('/account').data
        assert b'deleteBtn' in page, who
        assert (b'Provider profile' in page) == (who == 'doc'), who
    assert flask_app.test_client().get('/account').status_code == 302   # signed out


def test_provider_and_family_can_delete_their_accounts(world):
    ids, c = world
    for who in ('doc', 'mom'):
        assert c[who].post('/api/me/delete').status_code == 200, who
    assert c['pat'].get('/api/care-team').json['links'] == []


def test_new_provider_must_add_organization_first():
    uid = make_user('provider', 'newdoc')
    c = client_for(uid)
    r = c.get('/provider')
    assert r.status_code == 302 and '/account' in r.headers['Location']
    r = c.post('/account?next=/provider', data={'organization': '  ', 'specialty': 'Therapist'})
    assert r.status_code == 400 and b'Therapist' in r.data      # error keeps what they typed
    r = c.post('/account?next=/provider', data={'organization': 'Mercy Clinic', 'specialty': 'Therapist'})
    assert r.headers['Location'].endswith('/provider')
    assert c.get('/provider').status_code == 200


def test_unverified_provider_consent_leads_to_profile():
    with flask_app.app_context():
        u = User(google_sub='sub-gmaildoc', role='provider', email='gmaildoc@gmail.com', email_verified=True)
        db.session.add(u)
        db.session.commit()
        uid = u.id
    r = client_for(uid).post('/welcome', data={'agree': 'yes'})
    assert '/account' in r.headers['Location']


def test_demo_provider_is_verified_and_skips_profile_form():
    c = flask_app.test_client()
    c.get(c.get('/login?role=provider').headers['Location'])
    assert c.post('/welcome', data={'agree': 'yes'}).headers['Location'].endswith('/provider')
    page = c.get('/account').data
    assert b'City General Hospital' in page and b'readonly' in page


def test_only_providers_save_a_profile(world):
    ids, c = world
    assert c['pat'].post('/account', data={'organization': 'X'}).status_code == 403
    assert c['mom'].post('/account', data={'organization': 'X'}).status_code == 403


def test_patient_sees_provider_details(world):
    ids, c = world
    member = next(l['member'] for l in c['pat'].get('/api/care-team').json['links']
                  if l['member']['role'] == 'provider')
    assert member['organization'] == 'City Hospital' and member['specialty'] == 'Psychiatrist'
    doc = c['doc'].post(f"/api/patients/{ids['pat']}/documents", json={'title': 'Notes'}).json['document']
    assert doc['author_name'] == 'Doc, Psychiatrist, City Hospital (Health provider)'


# ---------- verified organisations (data/verified_organizations.csv) ----------

def test_organization_for_email_matching():
    assert organization_for_email('dr.lee@cityhospital.example') == 'City General Hospital'
    assert organization_for_email('a@psych.cityhospital.example') == 'City General Hospital'   # subdomain
    assert organization_for_email('DR@CITYHOSPITAL.EXAMPLE') == 'City General Hospital'
    for email in ('x@evilcityhospital.example', 'x@cityhospital.example.com', 'x@gmail.com', '', None, 'no-at'):
        assert organization_for_email(email) is None, email


def _provider(email, verified=True, organization=None):
    with flask_app.app_context():
        u = User(google_sub=f'sub-{email}', role='provider', name='Dr Lee', email=email,
                 email_verified=verified, organization=organization, terms_accepted_at=_now())
        db.session.add(u)
        db.session.commit()
        return u.id


def test_verified_provider_gets_org_and_badge():
    from auth import _finish_sign_in
    uid = _provider('dr.lee@cityhospital.example', organization='Somewhere Else')
    pat = make_user('patient', 'pat')
    with flask_app.test_request_context():
        _finish_sign_in(db.session.get(User, uid), 'provider', '/')
        assert db.session.get(User, uid).organization == 'City General Hospital'   # overrides the claim
    c = client_for(pat)
    c.post('/api/care-team', json={'email': 'dr.lee@cityhospital.example'})
    assert c.get('/api/care-team').json['links'][0]['member']['verified'] is True


def test_verified_provider_cannot_change_org():
    uid = _provider('dr.lee@cityhospital.example', organization='City General Hospital')
    c = client_for(uid)
    c.post('/account', data={'organization': 'Fake Hospital', 'specialty': 'Therapist'})
    with flask_app.app_context():
        u = db.session.get(User, uid)
        assert u.organization == 'City General Hospital' and u.specialty == 'Therapist'


def test_unverified_email_or_lookalike_is_not_verified():
    for email, verified in (('dr@cityhospital.example', False), ('dr@evilcityhospital.example', True)):
        uid = _provider(email, verified=verified, organization='City General Hospital')
        with flask_app.app_context():
            assert db.session.get(User, uid).is_verified_provider is False, email


def test_self_reported_provider_shows_unverified(world):
    ids, c = world
    assert c['pat'].get('/api/care-team').json['links'][0]['member']['verified'] is False


# ---------- dashboard (frontend/test.html) and mood colors ----------

def test_dashboard_is_patient_only(world):
    ids, c = world
    assert c['pat'].get('/test').status_code == 200
    assert c['pat'].get('/dashboard').headers['Location'].endswith('/test')
    assert c['doc'].get('/test').status_code == 302          # redirected to their own home
    assert '/signin' in flask_app.test_client().get('/test').headers['Location'] or \
        '/login' in flask_app.test_client().get('/test').headers['Location']


def test_api_me(world):
    ids, c = world
    me = c['pat'].get('/api/me').json
    assert me['name'] == 'Pat' and me['role'] == 'patient' and me['mood'] is None
    assert c['doc'].get('/api/me').json['role'] == 'provider'
    assert flask_app.test_client().get('/api/me').status_code == 401


def test_moods_save_merge_and_history(world):
    from datetime import timedelta
    from models import MoodEntry
    ids, c = world
    assert c['pat'].post('/api/moods', json={'color': 'Orange'}).status_code == 400
    assert c['pat'].post('/api/moods', json={'color': 'Blue'}).status_code == 201
    assert c['pat'].post('/api/moods', json={'color': 'Red'}).status_code == 200   # quick re-pick replaces
    assert [m['color'] for m in c['pat'].get('/api/moods').json['moods']] == ['Red']
    with flask_app.app_context():                       # pretend the last pick was 10 minutes ago
        m = MoodEntry.query.one()
        m.created_at = _now() - timedelta(minutes=10)
        db.session.commit()
    assert c['pat'].post('/api/moods', json={'color': 'Green'}).status_code == 201
    assert [m['color'] for m in c['pat'].get('/api/moods').json['moods']] == ['Red', 'Green']
    assert c['pat'].get('/api/me').json['mood']['color'] == 'Green'
    assert c['pat'].get('/api/moods').json['moods'][-1]['meaning'] == 'Calm and steady'
    for who in ('doc', 'mom'):
        assert c[who].post('/api/moods', json={'color': 'Blue'}).status_code == 403
    assert c['pat'].post('/api/me/delete').status_code == 200
    with flask_app.app_context():
        assert MoodEntry.query.count() == 0


def test_patient_lands_on_dashboard_after_sign_in():
    c = flask_app.test_client()
    c.get(c.get('/login?role=patient').headers['Location'])
    assert c.post('/welcome', data={'agree': 'yes'}).headers['Location'].endswith('/test')


def test_home_sends_patients_to_dashboard(world):
    ids, c = world
    assert c['pat'].get('/').headers['Location'].endswith('/test')
    assert c['doc'].get('/').status_code == 200                       # others keep the welcome page
    assert flask_app.test_client().get('/').status_code == 200
    page = c['pat'].get('/test').data
    for link in (b'#mood-history', b'#chatbot', b'#toolkit', b'#care-team', b'#settings', b'action="/logout"'):
        assert link in page, link


def test_dashboard_loads_test_js(world):
    ids, c = world
    page = c['pat'].get('/test').data
    assert b'<script src="test.js"' in page and b'static/css/attune.css' in page   # relative, so it also opens from disk
    r = flask_app.test_client().get('/test.js')
    assert r.status_code == 200 and 'javascript' in r.content_type
    assert b'/api/moods' in r.data and b'speechSynthesis' in r.data


# ---------- Text-message alerts ----------

@pytest.fixture
def texts(monkeypatch):
    """Capture texts instead of sending them (and send alert texts right away, not in a thread)."""
    import sms
    sent = []
    monkeypatch.setattr(sms, 'twilio_configured', lambda: True)
    monkeypatch.setattr(sms, 'send_sms', lambda to, body: sent.append((to, body)) or 'SMtest')
    monkeypatch.setattr(sms, 'dispatch', lambda messages: sent.extend(messages))
    return sent


def _confirm_phone(client, texts, phone='555-123-4567'):
    assert client.post('/api/me/phone', json={'phone': phone}).status_code == 200
    code = texts[-1][1].split('code is ')[1][:6]
    return client.post('/api/me/phone/verify', json={'code': code})


def test_normalize_phone():
    import sms
    assert sms.normalize_phone('(555) 123-4567') == '+15551234567'
    assert sms.normalize_phone('1 555 123 4567') == '+15551234567'
    assert sms.normalize_phone('+44 20 7946 0958') == '+442079460958'
    assert sms.normalize_phone('12345') is None
    assert sms.normalize_phone('') is None


def test_family_confirms_phone_and_gets_alert_texts(world, texts):
    ids, c = world
    res = _confirm_phone(c['mom'], texts)
    assert res.status_code == 200
    assert res.get_json()['phone'].endswith('4567')
    texts.clear()

    assert c['pat'].post('/api/alerts/sos', json={'kind': 'panic_attack', 'note': 'private note'}).status_code == 201
    assert len(texts) == 1
    to, body = texts[0]
    assert to == '+15551234567'
    assert 'Pat' in body and 'Panic attack' in body
    assert 'private note' not in body          # notes never go in texts


def test_wrong_code_does_not_save_phone(world, texts):
    ids, c = world
    c['mom'].post('/api/me/phone', json={'phone': '5551234567'})
    assert c['mom'].post('/api/me/phone/verify', json={'code': '000000' if '000000' not in texts[-1][1] else '111111'}).status_code == 400
    assert c['mom'].get('/api/me/phone').get_json()['phone'] is None


def test_too_many_wrong_codes_locks_out(world, texts):
    ids, c = world
    c['mom'].post('/api/me/phone', json={'phone': '5551234567'})
    real = texts[-1][1].split('code is ')[1][:6]
    wrong = '000000' if real != '000000' else '111111'
    for _ in range(5):
        c['mom'].post('/api/me/phone/verify', json={'code': wrong})
    assert c['mom'].post('/api/me/phone/verify', json={'code': real}).status_code == 429


def test_no_texts_when_turned_off_or_unlinked(world, texts):
    ids, c = world
    _confirm_phone(c['mom'], texts)
    _confirm_phone(c['stranger'], texts, '555-999-0000')    # not on pat's care team
    c['mom'].patch('/api/me/phone', json={'sms_alerts': False})
    texts.clear()
    c['pat'].post('/api/alerts/sos', json={'kind': 'crisis'})
    assert texts == []


def test_only_family_can_add_a_phone(world, texts):
    ids, c = world
    for who in ('pat', 'doc'):
        assert c[who].post('/api/me/phone', json={'phone': '5551234567'}).status_code == 403


def test_patient_app_settings_api(world):
    ids, c = world
    me = c['pat'].get('/api/me').json
    assert me['auto_alerts'] is True and me['save_expressions'] is False
    r = c['pat'].patch('/api/me/settings', json={'save_expressions': True})
    assert r.json['save_expressions'] is True and c['pat'].get('/api/me').json['save_expressions'] is True


def test_new_look_on_server_pages(world):
    ids, c = world
    for who, url in (('doc', '/provider'), ('mom', '/family'), ('doc', '/account')):
        page = c[who].get(url).data
        assert b'css/attune.css' in page and b'site.css' not in page and b'id="menuBtn"' in page, url
    assert b'img/logo.png' in flask_app.test_client().get('/').data


# ---------- Spotify music card (/api/music) ----------

def test_music_without_spotify_keys(world, monkeypatch):
    ids, c = world
    monkeypatch.delenv('SPOTIFY_CLIENT_ID', raising=False)
    r = c['pat'].get('/api/music?mood=Blue').json
    assert r['configured'] is False and r['playlists'] == [] and 'open.spotify.com/search/' in r['search_url']
    assert c['pat'].get('/api/music?mood=Orange').status_code == 400
    assert flask_app.test_client().get('/api/music').status_code == 401


def test_music_with_spotify(world, monkeypatch):
    import spotify
    ids, c = world
    monkeypatch.setenv('SPOTIFY_CLIENT_ID', 'id')
    monkeypatch.setenv('SPOTIFY_CLIENT_SECRET', 'secret')
    monkeypatch.setattr(spotify, '_cache', {})
    seen = []
    def fake_search(query, limit=6):
        seen.append(query)
        return [{'id': 'abc', 'name': 'Calm', 'owner': 'Spotify', 'image': None,
                 'url': 'https://open.spotify.com/playlist/abc', 'embed_url': 'https://open.spotify.com/embed/playlist/abc'}]
    monkeypatch.setattr(spotify, '_search', fake_search)
    r = c['pat'].get('/api/music?mood=Red').json
    assert r['playlists'][0]['embed_url'].endswith('/embed/playlist/abc')
    c['pat'].get('/api/music?mood=Red')
    assert seen == ['calming meditation breathing']          # second call served from cache
    def broken(query, limit=6): raise OSError('network down')
    monkeypatch.setattr(spotify, '_search', broken)
    r = c['pat'].get('/api/music?mood=Blue').json
    assert r['playlists'] == [] and 'error' in r


# ---------- Phone push notifications (ntfy) ----------

@pytest.fixture
def pushes(monkeypatch):
    import push
    sent = []
    monkeypatch.setattr(push, 'send_push', lambda topic, title, message, click=None, urgent=False:
                        sent.append(dict(topic=topic, title=title, message=message)))
    monkeypatch.setattr(push, 'dispatch', lambda notifications: sent.extend(notifications))
    return sent


def test_family_gets_push_notifications(world, pushes):
    ids, c = world
    state = c['mom'].post('/api/me/push').get_json()
    assert state['on'] and state['topic'].startswith('attune-')
    assert c['mom'].post('/api/me/push').get_json()['topic'] == state['topic']   # stays the same
    assert c['mom'].post('/api/me/push/test').status_code == 200
    pushes.clear()

    c['pat'].post('/api/alerts/sos', json={'kind': 'crisis', 'note': 'private note'})
    assert len(pushes) == 1
    assert pushes[0]['topic'] == state['topic']
    assert 'Crisis' in pushes[0]['title'] and 'Pat' in pushes[0]['title']
    assert 'private note' not in pushes[0]['message']


def test_push_topic_can_be_replaced_and_turned_off(world, pushes):
    ids, c = world
    first = c['mom'].post('/api/me/push').get_json()['topic']
    assert c['mom'].post('/api/me/push', json={'new': True}).get_json()['topic'] != first
    assert c['mom'].delete('/api/me/push').get_json()['on'] is False
    pushes.clear()
    c['pat'].post('/api/alerts/sos', json={'kind': 'crisis'})
    assert pushes == []


def test_unlinked_family_gets_no_push(world, pushes):
    ids, c = world
    c['stranger'].post('/api/me/push')
    pushes.clear()
    c['pat'].post('/api/alerts/sos', json={'kind': 'crisis'})
    assert pushes == []


def test_only_family_can_turn_on_push(world, pushes):
    ids, c = world
    for who in ('pat', 'doc'):
        assert c[who].post('/api/me/push').status_code == 403


# ---------- aura mood from chat ----------

def test_chat_returns_a_mood_for_the_aura(world):
    ids, c = world
    assert chat(c['pat'], 'I feel so lonely today').json['mood'] == 'lonely'
    assert chat(c['pat'], 'what is grounding?').json['mood'] is None
    assert chat(flask_app.test_client(), 'I am stressed').json['mood'] == 'stressed'   # signed out works too
