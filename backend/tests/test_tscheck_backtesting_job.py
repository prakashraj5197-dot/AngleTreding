"""Criterion: Backtesting runs as a background job and reports look-ahead-free results with costs separated."""

import time


def _wait_for_completion(client, job_id, timeout_s=90):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        r = client.get(f"/backtest/jobs/{job_id}")
        assert r.status_code == 200
        last = r.json()
        if last["status"] in ("COMPLETED", "FAILED"):
            return last
        time.sleep(2)
    raise AssertionError(f"job did not finish in {timeout_s}s, last={last}")


def test_backtest_run_completes_with_separated_costs(client):
    payload = {
        "symbol": "NIFTY",
        "from_date": "2025-06-01",
        "to_date": "2025-09-01",
        "timeframe": "5m",
        "strategy": "QuantPulse Momentum",
        "initial_capital": 500000.0,
        "risk_per_trade_pct": 1.0,
        "daily_loss_limit_pct": 2.0,
        "slippage_pct": 0.1,
        "brokerage_per_order": 20.0,
        "charges_pct": 0.05,
        "conservative_same_candle_rule": True,
    }
    run = client.post("/backtest/run", json=payload)
    assert run.status_code == 200, run.text[:300]
    job = run.json()
    job_id = job["id"]
    assert job["status"] in ("QUEUED", "RUNNING", "COMPLETED")

    result = _wait_for_completion(client, job_id)
    assert result["status"] == "COMPLETED", result.get("error")

    m = result.get("metrics")
    assert m, "completed job missing metrics"
    for field in ["total_trades", "wins", "losses", "win_rate", "profit_factor",
                  "avg_r", "max_drawdown", "gross_pnl", "total_costs", "net_pnl", "monthly"]:
        assert field in m, f"metrics missing field {field}"
    assert m["gross_pnl"] != m["net_pnl"], "gross and net pnl should be distinct once costs applied"
    assert m["net_pnl"] == round(m["gross_pnl"] - m["total_costs"], 2) or abs(
        m["net_pnl"] - (m["gross_pnl"] - m["total_costs"])
    ) < 1.0

    trades = client.get(f"/backtest/jobs/{job_id}/trades")
    assert trades.status_code == 200
    trade_rows = trades.json()
    if trade_rows:
        row = trade_rows[0]
        for field in ["entry_ts", "exit_ts", "side", "strike", "qty", "entry_price",
                      "exit_price", "sl", "target", "pnl", "r_multiple", "exit_reason", "segment"]:
            assert field in row, f"trade log missing field {field}: {row}"

    assert result.get("warnings"), "expected assumption/limitation warnings on completed job"


def test_previous_runs_listed(client):
    resp = client.get("/backtest/jobs")
    assert resp.status_code == 200
    jobs = resp.json()
    completed = [j for j in jobs if j["status"] == "COMPLETED"]
    assert len(completed) >= 1
