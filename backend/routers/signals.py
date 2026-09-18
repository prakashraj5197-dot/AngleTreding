"""Signal routes: engine state, signal list/detail/analytics, manual evaluation, notifications."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from lib.db import db
from lib.dates import UTC, now_utc
from lib.signal_engine import ANALYSIS_SYMBOLS, evaluate_symbol, get_settings, notify
from lib.sim_provider import INSTRUMENTS
from models.trading import EngineState, EvaluateRequest, NotificationOut, Signal

router = APIRouter(tags=["signals"])


def _strip(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


@router.get("/engine/state", response_model=list[EngineState])
async def engine_states(symbols: str = Query(",".join(ANALYSIS_SYMBOLS))):
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    out: list[EngineState] = []
    for sym in wanted:
        doc = await db.engine_state.find_one({"symbol": sym})
        if doc:
            out.append(EngineState(**_strip(doc)))
    return out


@router.post("/engine/evaluate", response_model=list[EngineState])
async def evaluate(body: EvaluateRequest | None = None):
    """Force one evaluation cycle now (the scheduler also runs it automatically)."""
    s = await get_settings()
    targets = [body.symbol.upper()] if body and body.symbol else list(ANALYSIS_SYMBOLS)
    for sym in targets:
        if sym not in INSTRUMENTS:
            raise HTTPException(status_code=404, detail=f"Unknown symbol '{sym}'.")
    return [await evaluate_symbol(sym, s) for sym in targets]


@router.get("/signals", response_model=list[Signal])
async def list_signals(
    status: str | None = None,
    symbol: str | None = None,
    option_type: str | None = None,
    result: str | None = None,
    strategy: str | None = None,
    min_score: float | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 200,
):
    q: dict = {}
    if status:
        q["status"] = {"$in": [s.strip().upper() for s in status.split(",")]}
    if symbol:
        q["symbol"] = symbol.upper()
    if option_type:
        q["option_type"] = option_type.upper()
    if result:
        q["result"] = {"$in": [r.strip().upper() for r in result.split(",")]}
    if strategy:
        q["strategy_name"] = strategy
    if min_score is not None:
        q["score"] = {"$gte": min_score}
    if from_date or to_date:
        rng: dict = {}
        if from_date:
            rng["$gte"] = from_date
        if to_date:
            rng["$lte"] = to_date
        q["day_ist"] = rng
    docs = await db.signals.find(q).sort("created_at", -1).limit(min(max(limit, 1), 500)).to_list(500)
    return [Signal(**_strip(d)) for d in docs]


@router.get("/signals/active", response_model=list[Signal])
async def active_signals():
    docs = await db.signals.find({"status": {"$in": ["ACTIVE", "TARGET1_HIT"]}}) \
        .sort("created_at", -1).to_list(50)
    return [Signal(**_strip(d)) for d in docs]


@router.get("/signals/analytics")
async def analytics(symbol: str | None = None):
    q: dict = {}
    if symbol:
        q["symbol"] = symbol.upper()
    docs = await db.signals.find(q).to_list(2000)
    closed = [d for d in docs if d.get("result") in ("WIN", "LOSS")]
    wins = [d for d in closed if d["result"] == "WIN"]
    losses = [d for d in closed if d["result"] == "LOSS"]
    pnls = [(d.get("pnl_points") or 0.0) for d in closed]
    gains = [p for p in pnls if p > 0]
    drops = [p for p in pnls if p < 0]
    r_vals = []
    for d in closed:
        risk = (d.get("entry_price") or d["entry_max"]) - d["stop_loss"]
        if risk > 0:
            r_vals.append((d.get("pnl_points") or 0.0) / risk)
    by_setup: dict[str, dict] = {}
    for d in closed:
        key = f"{d['symbol']} {d['option_type']}"
        rec = by_setup.setdefault(key, {"setup": key, "trades": 0, "wins": 0, "pnl": 0.0})
        rec["trades"] += 1
        rec["wins"] += 1 if d["result"] == "WIN" else 0
        rec["pnl"] = round(rec["pnl"] + (d.get("pnl_points") or 0.0), 2)
    for rec in by_setup.values():
        rec["win_rate"] = round(rec["wins"] / rec["trades"] * 100, 1)
    setups = sorted(by_setup.values(), key=lambda r: r["pnl"], reverse=True)
    # equity curve in premium points
    curve = []
    running = 0.0
    for d in sorted(closed, key=lambda x: x.get("exit_time") or x["created_at"]):
        running += d.get("pnl_points") or 0.0
        curve.append({"t": (d.get("exit_time") or d["created_at"]).isoformat(), "cum": round(running, 2)})
    peak = 0.0
    max_dd = 0.0
    run = 0.0
    for p in pnls:
        run += p
        peak = max(peak, run)
        max_dd = max(max_dd, peak - run)
    return {
        "total_signals": len(docs),
        "closed": len(closed),
        "active": sum(1 for d in docs if d.get("status") in ("ACTIVE", "TARGET1_HIT")),
        "no_fill": sum(1 for d in docs if d.get("result") == "MISSED_ENTRY"),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
        "avg_r": round(sum(r_vals) / len(r_vals), 3) if r_vals else 0.0,
        "profit_factor": round(sum(gains) / abs(sum(drops)), 2) if drops and sum(drops) != 0 else (999.0 if gains else 0.0),
        "total_points": round(sum(pnls), 2),
        "max_drawdown_points": round(max_dd, 2),
        "best_setup": setups[0] if setups else None,
        "worst_setup": setups[-1] if len(setups) > 1 else None,
        "setups": setups,
        "equity_curve": curve[-300:],
    }


@router.get("/signals/{signal_id}", response_model=Signal)
async def signal_detail(signal_id: str):
    doc = await db.signals.find_one({"id": signal_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Signal not found.")
    return Signal(**_strip(doc))


@router.post("/signals/{signal_id}/cancel", response_model=Signal)
async def cancel_signal(signal_id: str):
    doc = await db.signals.find_one({"id": signal_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Signal not found.")
    if doc["status"] not in ("ACTIVE", "TARGET1_HIT"):
        raise HTTPException(status_code=409, detail=f"Signal is {doc['status']} and cannot be cancelled.")
    events = list(doc.get("event_log", []))
    events.append({"ts": now_utc(), "event": "CANCELLED", "detail": "Cancelled manually from the Live Signals page."})
    await db.signals.update_one({"id": signal_id}, {"$set": {
        "status": "CANCELLED", "result": "FLAT", "updated_at": now_utc(),
        "exit_time": now_utc(), "exit_price": doc.get("option_ltp"), "event_log": events}})
    return Signal(**_strip(await db.signals.find_one({"id": signal_id})))


@router.get("/notifications", response_model=list[NotificationOut])
async def notifications(limit: int = 30, unread_only: bool = False):
    q = {"read": False} if unread_only else {}
    docs = await db.notifications.find(q).sort("ts", -1).limit(min(limit, 100)).to_list(100)
    return [NotificationOut(**_strip(d)) for d in docs]


@router.post("/notifications/read-all")
async def mark_all_read():
    res = await db.notifications.update_many({"read": False}, {"$set": {"read": True}})
    return {"updated": res.modified_count}
