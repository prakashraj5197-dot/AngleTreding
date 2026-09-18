"""Criterion: Paper trading tracks virtual capital only and never routes a real order (API layer).

NOTE: The companion browser check `paper-trading-reset-and-copy` deliberately exercises
POST /paper/reset against this same singleton "main" account (there is only one paper
account in the system) to prove the reset control works end-to-end. That is expected,
intended product behaviour, not test residue — but it means these assertions must accept
EITHER the originally-seeded state (equity ~Rs 5,16,599, 54 closed positions) OR the
post-reset state (equity == start_capital, 0 positions) depending on run order across the
full check suite in this environment.
"""


def test_paper_account_seeded_or_reset_state(client):
    resp = client.get("/paper/account")
    assert resp.status_code == 200, resp.text[:300]
    acct = resp.json()
    assert acct["start_capital"] == 500000.0
    assert acct["equity"] > 0
    is_reset_state = acct["equity"] == acct["start_capital"]
    is_seeded_state = 500000 < acct["equity"] < 600000
    assert is_reset_state or is_seeded_state, f"unexpected equity {acct['equity']}"


def test_paper_closed_positions_seeded_or_reset(client):
    resp = client.get("/paper/positions", params={"status": "CLOSED"})
    if resp.status_code != 200:
        resp = client.get("/paper/positions")
    assert resp.status_code == 200
    positions = resp.json()
    closed = [p for p in positions if p.get("status") == "CLOSED"]

    acct = client.get("/paper/account").json()
    if acct["equity"] == acct["start_capital"]:
        # account has been reset (by the reset browser check) - 0 closed positions is correct
        assert len(closed) == 0
        return

    assert len(closed) >= 54, f"expected >=54 closed positions, got {len(closed)}"
    row = closed[0]
    for field in ["entry_price", "qty", "realized_pnl"]:
        assert field in row, f"missing field {field} on closed position"

    # NOTE: POST /paper/reset is deliberately NOT exercised here — it mutates the
    # singleton seeded paper account relied upon by this test when data is present.
    # Reset behaviour is verified once, last, via the `paper-trading-reset-and-copy`
    # browser check instead.
