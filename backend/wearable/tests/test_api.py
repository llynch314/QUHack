"""Ingest, devices, access rules, escalation and patient rights (PRD §5A.6, §6.6, §8)."""
from datetime import datetime, timedelta, timezone

from models import Alert, HealthDocument, User, db
from wearable import escalation, security, simulator
from wearable.models import AuditLog, VitalSample, WearableAlert, WearableNudge


def iso(dt=None):
    return (dt or datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ')


def payload(**over):
    now = iso()
    p = {'source': 'apple_watch', 'sent_at': now,
         'samples': [{'type': 'heart_rate', 'value': 72, 'ts': now}, {'type': 'hrv_sdnn', 'value': '41', 'ts': now}]}
    p.update(over)
    return p


def ingest(client, token, body):
    return client.post('/api/wearable/ingest', json=body, headers={'X-Device-Token': token})


# ---------- devices & ingest ----------

def test_device_token_shown_once_and_only_hash_stored(patient_client, device_token):
    from wearable.models import WearableDevice
    d = WearableDevice.query.one()
    assert d.token_hash == security.hash_token(device_token) and device_token not in d.token_hash
    listed = patient_client.get('/api/wearable/devices').json['devices'][0]
    assert 'token' not in listed and 'token_hash' not in listed


def test_device_requires_consent(app):
    c = app.test_client()
    c.get('/wearable/dev-login/patient')
    r = c.post('/api/wearable/devices', json={})
    assert r.status_code == 403 and r.json['consent_required']


def test_ingest_ok(client, device_token):
    r = ingest(client, device_token, payload())
    assert r.status_code == 200, r.json
    assert r.json['inserted'] == 2 and r.json['state']['state'] in ('calm', 'elevated')


def test_bad_token_401(client, device_token):
    assert ingest(client, 'nope', payload()).status_code == 401
    assert client.post('/api/wearable/ingest', json=payload()).status_code == 401


def test_revoked_token_401_immediately(patient_client, device_token):
    assert ingest(patient_client, device_token, payload()).status_code == 200
    dev_id = patient_client.get('/api/wearable/devices').json['devices'][0]['id']
    assert patient_client.delete(f'/api/wearable/devices/{dev_id}').status_code == 200
    assert ingest(patient_client, device_token, payload()).status_code == 401


def test_bad_payloads_400(client, device_token):
    now = iso()
    assert ingest(client, device_token, payload(samples=[{'type': 'blood_type', 'value': 1, 'ts': now}])).status_code == 400
    assert ingest(client, device_token, {'samples': [{'type': 'heart_rate', 'value': 70, 'ts': now}]}).status_code == 400
    assert ingest(client, device_token, payload(samples=[{'type': 'heart_rate', 'value': 'abc', 'ts': now}])).status_code == 400
    assert ingest(client, device_token, payload(samples=[{'type': 'heart_rate', 'value': 900, 'ts': now}])).status_code == 400
    r = client.post('/api/wearable/ingest', data='not json', headers={'X-Device-Token': device_token,
                                                                       'Content-Type': 'application/json'})
    assert r.status_code == 400


def test_replay_old_sent_at_rejected(client, device_token):
    old = iso(datetime.now(timezone.utc) - timedelta(minutes=11))
    r = ingest(client, device_token, payload(sent_at=old))
    assert r.status_code == 400 and 'replay' in r.json['error']


def test_duplicates_ignored_and_out_of_order_ok(client, device_token):
    body = payload()
    assert ingest(client, device_token, body).json['inserted'] == 2
    r = ingest(client, device_token, body)
    assert r.json['inserted'] == 0 and r.json['duplicates'] == 2
    earlier = iso(datetime.now(timezone.utc) - timedelta(minutes=3))
    r = ingest(client, device_token, payload(samples=[{'type': 'heart_rate', 'value': 70, 'ts': earlier}]))
    assert r.json['inserted'] == 1
    assert VitalSample.query.count() == 3


def test_flat_shortcut_format_and_string_values(client, device_token):
    r = ingest(client, device_token, {'sent_at': iso(), 'heart_rate': '74 count/min', 'hrv_sdnn': '38.5', 'steps': 12})
    assert r.status_code == 200, r.json
    assert r.json['inserted'] == 3


def test_device_cannot_post_for_another_patient(app, patient_client, device_token):
    other = User(google_sub='other', name='Other Patient')
    db.session.add(other)
    db.session.commit()
    body = payload()
    body['patient_id'] = other.id     # ignored: the token decides the patient
    assert ingest(app.test_client(), device_token, body).status_code == 200
    assert VitalSample.query.filter_by(patient_id=other.id).count() == 0
    assert VitalSample.query.filter_by(patient_id=patient_client.patient.id).count() == 2


def test_rate_limit(client, device_token, monkeypatch):
    monkeypatch.setattr(security.ingest_limiter, 'limit', 3)
    codes = [ingest(client, device_token, payload(samples=[{'type': 'steps', 'value': i, 'ts': iso(
        datetime.now(timezone.utc) - timedelta(seconds=i))}])).status_code for i in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]


def test_payload_size_cap(client, device_token):
    big = payload(samples=[{'type': 'steps', 'value': 1, 'ts': iso()}] * 5000)
    assert ingest(client, device_token, big).status_code in (400, 413)


# ---------- transport ----------

def test_plain_http_from_network_403(client, device_token):
    r = client.post('/api/wearable/ingest', json=payload(), headers={'X-Device-Token': device_token},
                    environ_base={'REMOTE_ADDR': '192.168.1.50'})
    assert r.status_code == 403


def test_tunnel_over_http_403_and_https_200(client, device_token):
    r = client.post('/api/wearable/ingest', json=payload(), headers={'X-Device-Token': device_token,
                                                                     'X-Forwarded-Proto': 'http'})
    assert r.status_code == 403
    r = client.post('/api/wearable/ingest', json=payload(), headers={'X-Device-Token': device_token,
                                                                     'X-Forwarded-Proto': 'https'})
    assert r.status_code == 200
    assert 'Strict-Transport-Security' in r.headers


def test_spoofed_forwarded_https_from_lan_rejected(client, device_token):
    r = client.post('/api/wearable/ingest', json=payload(), headers={'X-Device-Token': device_token,
                    'X-Forwarded-Proto': 'https'}, environ_base={'REMOTE_ADDR': '192.168.1.50'})
    assert r.status_code == 403


def test_strict_mode_rejects_local_http(client, device_token, monkeypatch):
    monkeypatch.setenv('WEARABLE_REQUIRE_HTTPS', 'strict')
    assert ingest(client, device_token, payload()).status_code == 403
    r = client.post('/api/wearable/ingest', json=payload(), headers={'X-Device-Token': device_token},
                    base_url='https://localhost')
    assert r.status_code == 200


# ---------- access control ----------

def test_patient_reads_own_vitals(patient_client):
    pid = patient_client.patient.id
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'baseline'})
    assert patient_client.get(f'/api/patients/{pid}/state').status_code == 200
    v = patient_client.get(f'/api/patients/{pid}/vitals?range=1h')
    assert v.status_code == 200 and v.json['series']['heart_rate']


def test_family_cannot_read_vitals_and_is_audited(patient_client, family_client):
    pid = patient_client.patient.id
    for path in (f'/api/patients/{pid}/state', f'/api/patients/{pid}/vitals'):
        assert family_client.get(path).status_code == 403
    denied = AuditLog.query.filter_by(actor_id=family_client.user.id, outcome='denied').all()
    assert len(denied) >= 2 and all(a.actor_role == 'family' for a in denied)


def test_provider_cannot_read_vitals_but_can_read_report(patient_client, provider_client):
    pid = patient_client.patient.id
    assert provider_client.get(f'/api/patients/{pid}/state').status_code == 403
    assert AuditLog.query.filter_by(actor_id=provider_client.user.id, outcome='denied').count() >= 1
    rep = patient_client.post(f'/api/patients/{pid}/wearable-report').json['report']
    listed = provider_client.get('/api/wearable/reports')
    assert listed.status_code == 200 and listed.json['reports'][0]['category'] == 'wearable-report'
    r = provider_client.get(f'/api/wearable/reports/{rep["id"]}')
    assert r.status_code == 200 and '# Wearable report' in r.json['report']['body']


def test_provider_never_gets_alerts(patient_client, provider_client):
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'cardiac_warning'})
    assert provider_client.get('/api/wearable/alerts').status_code == 403


def test_family_cannot_read_reports(patient_client, family_client):
    patient_client.post(f'/api/patients/{patient_client.patient.id}/wearable-report')
    rep = HealthDocument.query.filter_by(category='wearable-report').first()
    assert family_client.get('/api/wearable/reports').status_code == 403
    assert family_client.get(f'/api/wearable/reports/{rep.id}').status_code == 403


def test_unlinked_patient_cannot_read_other_patient(app, patient_client):
    other = User(google_sub='other2', name='Other', terms_accepted_at=datetime.now(timezone.utc))
    db.session.add(other)
    db.session.commit()
    c = app.test_client()
    with c.session_transaction() as s:
        s['user_id'] = other.id
    assert c.get(f'/api/patients/{patient_client.patient.id}/state').status_code == 403


# ---------- escalation ----------

def test_exercise_triggers_no_alert_or_nudge(patient_client):
    r = patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'exercise'}).json
    assert r['state']['state'] == 'exercising' and r['alert'] is None
    assert WearableNudge.query.count() == 0 and WearableAlert.query.count() == 0


def test_stress_nudges_patient_only_and_dedupes(patient_client):
    for _ in range(2):
        r = patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'stress_spike'}).json
        assert r['state']['state'] == 'stressed' and r['alert'] is None
    assert WearableNudge.query.count() == 1
    assert WearableAlert.query.count() == 0


def test_tier2_family_alert_only_when_patient_opts_in(patient_client, family_client):
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'sustained_distress'})
    assert family_client.get('/api/wearable/alerts?unacknowledged=1').json['alerts'] == []
    patient_client.post('/api/wearable/demo/reset')
    patient_client.post('/api/wearable/profile', json={'family_tier2_alerts': True})
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'sustained_distress'})
    alerts = family_client.get('/api/wearable/alerts?unacknowledged=1').json['alerts']
    assert len(alerts) == 1 and alerts[0]['kind'] == 'distress'
    assert not any(ch.isdigit() for ch in alerts[0]['note'])   # generic text, no vitals


def test_fall_countdown_then_family_alert_and_ack(patient_client, family_client):
    r = patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'fall'}).json
    assert r['alert']['kind'] == 'fall' and r['alert']['status'] == 'pending'
    assert family_client.get('/api/wearable/alerts?unacknowledged=1').json['alerts'] == []
    later = datetime.now(timezone.utc) + timedelta(seconds=61)
    assert escalation.promote_due_alerts(now=later) == 1
    alerts = family_client.get('/api/wearable/alerts?unacknowledged=1').json['alerts']
    assert len(alerts) == 1 and 'possible fall' in alerts[0]['note']
    assert family_client.post(f'/api/wearable/alerts/{alerts[0]["id"]}/ack').json['alert']['status'] == 'acknowledged'
    assert family_client.get('/api/wearable/alerts?unacknowledged=1').json['alerts'] == []


def test_im_ok_cancels_fall_alert(patient_client, family_client):
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'fall'})
    r = patient_client.post('/api/wearable/feedback', json={'correction': 'im_ok'}).json
    assert r['cancelled_alerts'] == 1 and r['state']['state'] != 'emergency'
    escalation.promote_due_alerts(now=datetime.now(timezone.utc) + timedelta(seconds=120))
    assert family_client.get('/api/wearable/alerts').json['alerts'] == []


def test_cardiac_warning_alerts_family_immediately(patient_client, family_client):
    r = patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'cardiac_warning'}).json
    assert r['alert']['status'] == 'open'
    assert family_client.get('/api/wearable/alerts?unacknowledged=1').json['alerts'][0]['kind'] == 'cardiac_warning'


def test_emergency_alerts_toggle_off(patient_client, family_client):
    patient_client.post('/api/wearable/profile', json={'emergency_alerts': False})
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'cardiac_warning'})
    assert family_client.get('/api/wearable/alerts').json['alerts'] == []


def test_one_open_alert_per_kind_within_15_min(patient_client):
    for _ in range(3):
        patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'cardiac_warning'})
    assert WearableAlert.query.filter_by(kind='cardiac_warning').count() == 1


def test_report_auto_generated_after_tier2_or_3(patient_client):
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'exercise'})
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'fall'})
    rep = HealthDocument.query.filter_by(category='wearable-report').one()
    assert 'possible fall' in rep.body and 'Exercise correctly ignored' in rep.body
    assert rep.title.endswith('(possible fall)')


# ---------- demo mode, idle logoff ----------

def test_demo_endpoints_404_without_demo_mode(patient_client, monkeypatch):
    monkeypatch.setenv('DEMO_MODE', '0')
    assert patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'baseline'}).status_code == 404
    assert patient_client.post('/api/wearable/demo/reset').status_code == 404


def test_idle_logoff(patient_client, monkeypatch):
    pid = patient_client.patient.id
    with patient_client.session_transaction() as s:
        s['wearable_active_at'] = s['wearable_active_at'] - 16 * 60
    r = patient_client.get(f'/api/patients/{pid}/state')
    assert r.status_code == 401 and r.json['reauth']
    assert patient_client.get(f'/api/patients/{pid}/state').status_code == 401   # session cleared


def test_polling_does_not_keep_session_alive(patient_client):
    pid = patient_client.patient.id
    with patient_client.session_transaction() as s:
        before = s['wearable_active_at']
    patient_client.get(f'/api/patients/{pid}/state', headers={'X-Wearable-Poll': '1'})
    with patient_client.session_transaction() as s:
        assert s['wearable_active_at'] == before


# ---------- patient rights ----------

def test_export_contains_decrypted_data(patient_client):
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'baseline'})
    r = patient_client.get('/api/wearable/export')
    assert r.status_code == 200 and 'attachment' in r.headers['Content-Disposition']
    data = r.json
    assert data['samples'] and isinstance(data['samples'][0]['value'], float) and data['audit_log']


def test_delete_leaves_only_audit(patient_client, device_token):
    pid = patient_client.patient.id
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'fall'})
    assert patient_client.post('/api/wearable/delete', json={}).status_code == 400
    r = patient_client.post('/api/wearable/delete', json={'confirm': 'DELETE'})
    assert r.status_code == 200
    export = patient_client.get('/api/wearable/export').json
    for key in ('samples', 'events', 'states', 'alerts', 'reports', 'devices'):
        assert export[key] == [], key
    assert AuditLog.query.filter_by(patient_id=pid, action='delete_all_wearable_data').count() == 1
    assert ingest(patient_client, device_token, payload()).status_code == 401   # device removed


def test_pages_render_for_each_role(app, patient_client):
    assert b'Demo Control Panel' in patient_client.get('/wearable').data
    fam = app.test_client()
    assert fam.get('/wearable/dev-login/family').headers['Location'].endswith('/family')
    assert fam.get('/wearable').headers['Location'].endswith('/family')
    page = fam.get('/family').data
    assert b'Demo Patient' in page   # already on the demo patient's care team
    prov = app.test_client()
    loc = prov.get('/wearable/dev-login/provider').headers['Location']
    assert loc.endswith(f'/provider/patients/{patient_client.patient.id}')
    assert prov.get(loc).status_code == 200   # profile filled in, consent done, linked


# ---------- integration with the team's roles / alerts / documents ----------

def test_family_sees_watch_alert_on_team_alerts_page(patient_client, family_client):
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'cardiac_warning'})
    alerts = family_client.get('/api/alerts').json['alerts']
    assert len(alerts) == 1 and alerts[0]['source'] == 'wearable' and alerts[0]['kind'] == 'cardiac_warning'
    assert alerts[0]['label'] == 'Warning signs (watch)' and not any(ch.isdigit() for ch in alerts[0]['note'].replace('911', ''))
    # acknowledging on the team page shows up on the patient's watch page
    assert family_client.post(f'/api/alerts/{alerts[0]["id"]}/acknowledge').status_code == 200
    state = patient_client.get(f'/api/patients/{patient_client.patient.id}/state').json
    assert state['last_family_alert']['status'] == 'acknowledged'
    # and the patient sees it next to their other alerts
    assert patient_client.get('/api/alerts').json['alerts'][0]['source'] == 'wearable'


def test_fall_alert_reaches_team_page_without_patient_page_open(patient_client, family_client, monkeypatch):
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'fall'})
    assert family_client.get('/api/alerts').json['alerts'] == []
    monkeypatch.setattr(escalation, 'utcnow', lambda: datetime.now(timezone.utc) + timedelta(seconds=61))
    import wearable
    monkeypatch.setattr(wearable, 'PROMOTE_EVERY_S', 0)
    alerts = family_client.get('/api/alerts').json['alerts']   # only the family page is polling
    assert len(alerts) == 1 and alerts[0]['kind'] == 'fall'


def test_call_911_alerts_family_right_away(patient_client, family_client):
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'fall'})
    r = patient_client.post('/api/wearable/emergency/call').json
    assert r['family_alerted'] == 1 and r['family_count'] == 1 and r['demo_mode'] is True
    assert family_client.get('/api/alerts').json['alerts'][0]['kind'] == 'fall'
    assert AuditLog.query.filter_by(action='write_emergency_call').count() == 1


def test_no_family_on_care_team_is_reported(patient_client):
    from models import CareLink
    state = patient_client.get(f'/api/patients/{patient_client.patient.id}/state').json
    assert state['family_count'] == 1   # demo login puts Demo Family member on the care team
    CareLink.query.delete()
    db.session.commit()
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'cardiac_warning'})
    state = patient_client.get(f'/api/patients/{patient_client.patient.id}/state').json
    assert state['family_count'] == 0


def test_removed_family_member_loses_access(patient_client, family_client):
    from models import CareLink
    CareLink.query.filter_by(member_id=family_client.user.id).delete()
    db.session.commit()
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'cardiac_warning'})
    assert family_client.get('/api/alerts').json['alerts'] == []
    assert family_client.get('/api/wearable/alerts').json['alerts'] == []


def test_provider_sees_report_in_health_documents(patient_client, provider_client):
    pid = patient_client.patient.id
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'fall'})
    docs = provider_client.get(f'/api/patients/{pid}/documents').json['documents']
    assert any(d['category'] == 'wearable-report' and 'possible fall' in d['title'] for d in docs)
    assert provider_client.get('/api/alerts').status_code == 403   # providers never get alerts


def test_deleting_account_deletes_wearable_data(patient_client):
    pid = patient_client.patient.id
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'fall'})
    assert patient_client.post('/api/me/delete').status_code == 200
    assert VitalSample.query.filter_by(patient_id=pid).count() == 0
    assert WearableAlert.query.filter_by(patient_id=pid).count() == 0
    assert Alert.query.filter_by(patient_id=pid).count() == 0


def test_old_demo_accounts_get_their_role_fixed(app):
    db.session.add(User(google_sub='dev-demo-family', name='Old', email='x@example.com'))   # role defaults to patient
    db.session.commit()
    c = app.test_client()
    assert c.get('/wearable/dev-login/family').status_code == 302
    assert User.query.filter_by(google_sub='dev-demo-family').one().role == 'family'


def test_simulator_cli_dry_run(capsys):
    assert simulator.main(['--scenario', 'fall', '--dry-run']) == 0
    assert 'fall_detected' in capsys.readouterr().out


def test_timestamps_are_explicit_utc(patient_client):
    """Regression: SQLite returns naive datetimes; browsers would read them as local time."""
    pid = patient_client.patient.id
    patient_client.post('/api/wearable/demo/scenario', json={'scenario': 'fall'})
    state = patient_client.get(f'/api/patients/{pid}/state').json
    assert state['pending_alert']['send_at'].endswith('+00:00')
    assert state['nudge']['created_at'].endswith('+00:00')
    assert state['state']['ts'].endswith('+00:00')
    left = (datetime.fromisoformat(state['pending_alert']['send_at']) - datetime.now(timezone.utc)).total_seconds()
    assert 0 < left <= 60
