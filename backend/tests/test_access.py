"""Checks that each login type sees exactly what it should.  Run: pytest  (from backend/)"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gemini_backend  # noqa: E402
from app import create_app  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(gemini_backend, "generate_response",
                        lambda text, history=None, emotion=None: f"bot reply ({len(history or [])} prior)")
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "SECRET_KEY": "test"})
    return app.test_client()


def register(client, role, name):
    r = client.post("/api/auth/register", json={
        "email": f"{name}@example.com", "name": name.title(), "password": "password123", "role": role})
    assert r.status_code == 201, r.json
    return {"Authorization": f"Bearer {r.json['token']}"}, r.json["user"]["id"]


@pytest.fixture
def world(client):
    """A patient with a linked provider and family member, plus an unlinked outsider of each kind."""
    p, pid = register(client, "patient", "pat")
    dr, _ = register(client, "provider", "doc")
    fam, _ = register(client, "family", "mom")
    other_dr, _ = register(client, "provider", "otherdoc")
    other_fam, _ = register(client, "family", "stranger")
    other_p, other_pid = register(client, "patient", "otherpat")
    for email in ("doc@example.com", "mom@example.com"):
        assert client.post("/api/care-team", json={"email": email}, headers=p).status_code == 201
    return dict(client=client, p=p, pid=pid, dr=dr, fam=fam, other_dr=other_dr,
                other_fam=other_fam, other_p=other_p, other_pid=other_pid)


# ---------- auth ----------

def test_login_and_wrong_portal(client):
    register(client, "family", "mom")
    ok = client.post("/api/auth/login", json={"email": "mom@example.com", "password": "password123"})
    assert ok.status_code == 200 and ok.json["user"]["role"] == "family"
    bad_pw = client.post("/api/auth/login", json={"email": "mom@example.com", "password": "nope"})
    assert bad_pw.status_code == 401
    wrong_portal = client.post("/api/auth/login", json={
        "email": "mom@example.com", "password": "password123", "role": "patient"})
    assert wrong_portal.status_code == 403


def test_requires_login(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/alerts", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_bad_role_rejected(client):
    r = client.post("/api/auth/register", json={
        "email": "x@example.com", "name": "X", "password": "password123", "role": "admin"})
    assert r.status_code == 400


# ---------- documents: patient + linked provider only ----------

def test_documents_access(world):
    c, pid = world["client"], world["pid"]
    url = f"/api/patients/{pid}/documents"
    assert c.post(url, json={"title": "Intake form"}, headers=world["p"]).status_code == 201
    r = c.post(url, json={"title": "Session notes", "body": "..."}, headers=world["dr"])
    assert r.status_code == 201
    doc_id = r.json["document"]["id"]

    assert len(c.get(url, headers=world["p"]).json["documents"]) == 2
    assert len(c.get(url, headers=world["dr"]).json["documents"]) == 2
    for who in ("fam", "other_dr", "other_fam", "other_p"):
        assert c.get(url, headers=world[who]).status_code == 403, who
        assert c.get(f"/api/documents/{doc_id}", headers=world[who]).status_code == 403, who


def test_provider_can_only_delete_own_documents(world):
    c, pid = world["client"], world["pid"]
    url = f"/api/patients/{pid}/documents"
    mine = c.post(url, json={"title": "Patient's"}, headers=world["p"]).json["document"]["id"]
    theirs = c.post(url, json={"title": "Doctor's"}, headers=world["dr"]).json["document"]["id"]
    assert c.delete(f"/api/documents/{mine}", headers=world["dr"]).status_code == 403
    assert c.delete(f"/api/documents/{theirs}", headers=world["dr"]).status_code == 204


# ---------- alerts: patient + linked family only ----------

def test_alerts_access(world):
    c, pid = world["client"], world["pid"]
    r = c.post("/api/alerts/sos", json={"kind": "panic_attack", "note": "help"}, headers=world["p"])
    assert r.status_code == 201
    alert_id = r.json["alert"]["id"]

    assert len(c.get("/api/alerts", headers=world["fam"]).json["alerts"]) == 1
    assert len(c.get(f"/api/patients/{pid}/alerts", headers=world["fam"]).json["alerts"]) == 1
    assert c.get("/api/alerts", headers=world["other_fam"]).json["alerts"] == []
    assert c.get(f"/api/patients/{pid}/alerts", headers=world["other_fam"]).status_code == 403
    assert c.get("/api/alerts", headers=world["dr"]).status_code == 403
    assert c.get(f"/api/patients/{pid}/alerts", headers=world["dr"]).status_code == 403

    ack = c.post(f"/api/alerts/{alert_id}/acknowledge", headers=world["fam"])
    assert ack.status_code == 200 and ack.json["alert"]["acknowledged_by"] == "Mom"
    assert c.post(f"/api/alerts/{alert_id}/acknowledge",
                  headers=world["other_fam"]).status_code == 403


def test_only_patient_can_sos(world):
    assert world["client"].post("/api/alerts/sos", json={}, headers=world["fam"]).status_code == 403


# ---------- chat: patient only, auto-alerts family ----------

def test_chat_is_private(world):
    c = world["client"]
    for who in ("dr", "fam"):
        assert c.post("/api/chat", json={"message": "hi"}, headers=world[who]).status_code == 403
        assert c.get("/api/chat", headers=world[who]).status_code == 403


def test_chat_remembers_history(world):
    c = world["client"]
    c.post("/api/chat", json={"message": "hello"}, headers=world["p"])
    r = c.post("/api/chat", json={"message": "again"}, headers=world["p"])
    assert r.json["reply"] == "bot reply (2 prior)"
    assert len(c.get("/api/chat", headers=world["p"]).json["messages"]) == 4


def test_panic_in_chat_alerts_family_without_leaking_text(world):
    c = world["client"]
    r = c.post("/api/chat", json={"message": "I'm having a panic attack and can't breathe"},
               headers=world["p"])
    assert r.json["urgent"] == "panic_attack" and r.json["alert_sent"]
    alerts = c.get("/api/alerts", headers=world["fam"]).json["alerts"]
    assert len(alerts) == 1 and alerts[0]["kind"] == "panic_attack"
    assert "breathe" not in alerts[0]["note"]


def test_crisis_adds_resources(world):
    r = world["client"].post("/api/chat", json={"message": "I want to die"}, headers=world["p"])
    assert r.json["urgent"] == "crisis" and "988" in r.json["reply"]


def test_auto_alerts_can_be_turned_off(world):
    c = world["client"]
    c.patch("/api/auth/me", json={"auto_alerts": False}, headers=world["p"])
    r = c.post("/api/chat", json={"message": "total meltdown right now"}, headers=world["p"])
    assert r.json["urgent"] == "meltdown" and not r.json["alert_sent"]
    assert c.get("/api/alerts", headers=world["fam"]).json["alerts"] == []


# ---------- care team ----------

def test_removing_member_revokes_access(world):
    c, pid = world["client"], world["pid"]
    links = c.get("/api/care-team", headers=world["p"]).json["links"]
    doc_link = next(l for l in links if l["member"]["role"] == "provider")
    assert c.delete(f"/api/care-team/{doc_link['id']}", headers=world["p"]).status_code == 204
    assert c.get(f"/api/patients/{pid}/documents", headers=world["dr"]).status_code == 403


def test_care_team_rules(world):
    c = world["client"]
    # Only patients add people, and only providers/family can be added.
    assert c.post("/api/care-team", json={"email": "otherdoc@example.com"},
                  headers=world["fam"]).status_code == 403
    assert c.post("/api/care-team", json={"email": "otherpat@example.com"},
                  headers=world["p"]).status_code == 400
    # A provider sees which patients they're linked to.
    links = c.get("/api/care-team", headers=world["dr"]).json["links"]
    assert [l["patient"]["id"] for l in links] == [world["pid"]]
    # A patient can't remove someone else's link.
    assert c.delete(f"/api/care-team/{links[0]['id']}", headers=world["other_p"]).status_code == 404
