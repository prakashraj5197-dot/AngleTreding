"""Risk manager — config-driven signal gates (§17, §36.24–26).

Blocked signals are never "soft" warnings: the engine returns NO TRADE with the reason.
All limits are read from AppSettings.risk and can be changed from Settings without code
changes (AC-67); a signal that violates any enabled rule is not generated (AC-36).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from lib.db import db
from lib.dates import ist_date, ist_midnight_utc, now_utc
from models.trading import RiskSettings

ACTIVE_STATUSES = ["ACTIVE", "TARGET1_HIT"]


@dataclass
class RiskVerdict:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    trades_today: int = 0
    total_signals_today: int = 0
    consecutive_losses: int = 0
    daily_pnl: float = 0.0
    last_signal_at: datetime | None = None


async def risk_verdict(symbol: str, s: RiskSettings, strategy_name: str) -> RiskVerdict:
    today = ist_date()
    v = RiskVerdict(allowed=True)

    v.total_signals_today = await db.signals.count_documents({"day_ist": today})
    v.trades_today = await db.signals.count_documents(
        {"day_ist": today, "symbol": symbol, "strategy_name": strategy_name,
         "status": {"$nin": ["CANCELLED", "DATA_ERROR"]}})

    # closed-signal streak for consecutive losses (today only; resets next session — 36.26)
    recent = await db.signals.find(
        {"day_ist": today, "symbol": symbol, "strategy_name": strategy_name,
         "result": {"$in": ["WIN", "LOSS"]}},
        sort=[("exit_time", -1)], limit=10).to_list(10)
    streak = 0
    for sig in recent:
        if sig.get("result") == "LOSS":
            streak += 1
        else:
            break
    v.consecutive_losses = streak

    # paper ledger daily P&L (realized today + open unrealized) — the ₹ risk ledger
    since = ist_midnight_utc()
    closed_today = [p async for p in db.paper_positions.find(
        {"status": "CLOSED", "exit_time": {"$gte": since}})]
    open_pos = [p async for p in db.paper_positions.find({"status": "OPEN"})]
    v.daily_pnl = round(
        sum(p.get("realized_pnl") or 0 for p in closed_today) +
        sum(p.get("unrealized") or 0 for p in open_pos), 2)

    last = await db.signals.find_one(
        {"symbol": symbol, "strategy_name": strategy_name},
        sort=[("created_at", -1)])
    v.last_signal_at = last.get("created_at") if last else None

    if not s.enforce:
        return v

    if v.daily_pnl <= -abs(s.daily_loss_limit):
        v.allowed = False
        v.reasons.append(f"DAILY LOSS LIMIT REACHED — day P&L ₹{v.daily_pnl:,.0f} breached the ₹{s.daily_loss_limit:,.0f} limit. Trading paused for this session.")
    if streak >= s.consecutive_loss_limit:
        v.allowed = False
        v.reasons.append(f"TRADING PAUSED — {streak} consecutive losing trades (limit {s.consecutive_loss_limit}). Reset next session.")
    if v.trades_today >= s.max_trades_per_day:
        v.allowed = False
        v.reasons.append(f"Maximum trades per day reached for {symbol} ({v.trades_today}/{s.max_trades_per_day}).")
    if v.total_signals_today >= 2 * s.max_trades_per_day:
        v.allowed = False
        v.reasons.append(f"Maximum total signals per day reached ({v.total_signals_today}).")

    active = await db.signals.count_documents(
        {"symbol": symbol, "strategy_name": strategy_name, "status": {"$in": ACTIVE_STATUSES}})
    if active > 0:
        v.allowed = False
        v.reasons.append(f"An active signal already exists for {symbol} — duplicate setups blocked (cooldown).")

    return v
