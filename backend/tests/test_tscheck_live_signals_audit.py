"""Criterion: Live Signals page - seeded signal history, summary analytics and audit detail view (API layer)."""


def test_signals_analytics_seeded_totals(client):
    resp = client.get("/signals/analytics")
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["total_signals"] == 54, body
    assert body["active"] > 0 and body["closed"] > 0
    assert "win_rate" in body and "profit_factor" in body and "avg_r" in body


def test_signals_list_and_filters(client):
    resp = client.get("/signals")
    assert resp.status_code == 200
    signals = resp.json()
    assert len(signals) >= 54

    calls = client.get("/signals", params={"option_type": "CE"})
    if calls.status_code == 200:
        rows = calls.json()
        if rows:
            assert all(r["option_type"] == "CE" for r in rows), "CE filter leaked non-CE rows"

    puts = client.get("/signals", params={"option_type": "PE"})
    if puts.status_code == 200:
        rows = puts.json()
        if rows:
            assert all(r["option_type"] == "PE" for r in rows), "PE filter leaked non-PE rows"

    nifty = client.get("/signals", params={"symbol": "NIFTY"})
    if nifty.status_code == 200:
        rows = nifty.json()
        if rows:
            assert all(r["symbol"] == "NIFTY" for r in rows), "symbol filter leaked other symbols"


def test_signal_detail_has_audit_fields(client):
    listed = client.get("/signals").json()
    assert listed, "no seeded signals found"
    sig_id = listed[0]["id"]

    detail = client.get(f"/signals/{sig_id}")
    assert detail.status_code == 200, detail.text[:300]
    body = detail.json()

    for field in [
        "entry_min", "entry_max", "stop_loss", "target1", "target2",
        "risk_reward", "strength", "reasons", "strategy_name", "strategy_version",
        "option_ltp",
    ]:
        assert field in body, f"missing audit field: {field}"

    assert isinstance(body["reasons"], list) and len(body["reasons"]) > 0


def test_notifications_seeded(client):
    resp = client.get("/notifications", params={"limit": 200})
    assert resp.status_code == 200
    notes = resp.json()
    assert len(notes) >= 100, f"expected >=100 (2 per 54 signals), got {len(notes)}"
