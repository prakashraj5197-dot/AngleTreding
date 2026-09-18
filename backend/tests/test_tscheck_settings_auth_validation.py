"""Criterion: Settings requires admin auth, validates input, persists changes and mints a new version."""

import httpx


ADMIN_EMAIL = "admin@quantpulse.in"
ADMIN_PASSWORD = "QuantPulse@2026"


def test_unauthenticated_put_settings_rejected(client):
    resp = client.put("/settings", json={"strategy": {"min_signal_score": 55.0}})
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}: {resp.text[:300]}"


def test_login_then_persist_and_version_bump(client):
    login = client.post(
        "/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 200, f"login failed: {login.status_code} {login.text[:300]}"

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json().get("email") == ADMIN_EMAIL

    before = client.get("/settings").json()
    old_version = before["strategy"]["version"]
    old_score = before["strategy"]["min_signal_score"]
    new_score = 52.0 if old_score != 52.0 else 51.0

    payload = dict(before)
    payload["strategy"] = dict(before["strategy"])
    payload["strategy"]["min_signal_score"] = new_score

    put = client.put("/settings", json=payload)
    assert put.status_code == 200, f"PUT settings failed: {put.status_code} {put.text[:300]}"
    body = put.json()
    assert body["strategy"]["min_signal_score"] == new_score
    assert body["strategy"]["version"] != old_version, "strategy version must bump on save"

    # persists across a fresh read (simulating reload)
    after = client.get("/settings").json()
    assert after["strategy"]["min_signal_score"] == new_score
    assert after["strategy"]["version"] == body["strategy"]["version"]


def test_invalid_min_signal_score_rejected(client):
    login = client.post(
        "/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 200

    current = client.get("/settings").json()
    payload = dict(current)
    payload["strategy"] = dict(current["strategy"])
    payload["strategy"]["min_signal_score"] = 150.0  # invalid, > 100

    resp = client.put("/settings", json=payload)
    assert resp.status_code in (400, 422), (
        f"expected validation rejection, got {resp.status_code}: {resp.text[:300]}"
    )
