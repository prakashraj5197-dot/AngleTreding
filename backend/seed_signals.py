"""Replay recent sessions through the LIVE engine to build real signal history.

This is not fabricated data: every signal here is produced by the same
evaluate_direction → select_option → calc_levels → risk-gate pipeline the live
engine runs, fed candle-by-candle with data ≤ the decision timestamp. Outcomes are
resolved from the following candles (conservative same-candle rule), so the Live
Signals, History and Analytics pages open with genuine engine output.

Run: cd /app/backend && python seed_signals.py [--sessions 25]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timedelta

import numpy as np

from lib.db import db
from lib.dates import IST, SESSION_SECONDS, UTC, to_ist
from lib.engine import (
    Series,
    calc_levels,
    compute_indicators,
    evaluate_direction,
    option_symbol,
    select_option,
    strength_label,
)
from lib.option_math import bs_price, option_candles
from lib.sim_provider import INSTRUMENTS, SimulatedProvider
from models.trading import AppSettings


def day_of(ts: datetime) -> str:
    return to_ist(ts).strftime("%Y-%m-%d")


def _close_ts(ts: datetime, per: int) -> datetime:
    return ts + timedelta(minutes=per)


async def replay(symbol: str, sessions: int, settings: AppSettings) -> int:
    provider = SimulatedProvider()
    s = settings.strategy
    os_cfg = settings.option_selection
    lot = INSTRUMENTS[symbol].lot_size
    per = 5

    docs = await db.candles.find({"symbol": symbol, "timeframe": "5m"}) \
        .sort("ts", -1).limit(sessions * 75 + 400).to_list(sessions * 75 + 400)
    docs.reverse()
    if len(docs) < 300:
        return 0

    series = Series(
        ts=[d["ts"] if d["ts"].tzinfo else d["ts"].replace(tzinfo=UTC) for d in docs],
        o=np.array([d["o"] for d in docs]), h=np.array([d["h"] for d in docs]),
        l=np.array([d["l"] for d in docs]), c=np.array([d["c"] for d in docs]),
        v=np.array([d["v"] for d in docs]),
        session_ids=[day_of(d["ts"] if d["ts"].tzinfo else d["ts"].replace(tzinfo=UTC)) for d in docs],
    )
    ind = compute_indicators(series, s)
    n = len(docs)
    warmup = max(s.ema_slow + 5, 205, s.breakout_lookback + 1, s.rsi_period + 3)

    created = 0
    day_counts: dict[str, int] = {}
    cooldown_until: datetime | None = None

    for i in range(warmup, n - 1):
        close_ts = _close_ts(series.ts[i], per)
        ist_close = to_ist(close_ts)
        day = day_of(series.ts[i])
        elapsed = (ist_close.hour * 3600 + ist_close.minute * 60) - 9 * 3600 - 15 * 60
        if elapsed < s.opening_filter_min * 60 or elapsed > SESSION_SECONDS - s.closing_filter_min * 60:
            continue
        if cooldown_until and close_ts < cooldown_until:
            continue
        if day_counts.get(day, 0) >= s.max_signals_per_symbol_day:
            continue

        expiries = provider.next_expiries(symbol, ist_close)
        if not expiries:
            continue
        expiry = expiries[0]
        if expiry == ist_close.strftime("%Y-%m-%d") and elapsed > SESSION_SECONDS - s.expiry_day_filter_min * 60:
            if len(expiries) < 2:
                continue
            expiry = expiries[1]

        regime = provider._regime_for(symbol, day)
        spot = float(series.c[i])
        summary = provider.chain_summary(symbol, spot, day, close_ts, expiry, regime)
        direction = evaluate_direction(series, ind, summary, None, s, idx=i)
        if direction.direction not in ("BULLISH", "BEARISH"):
            continue

        chain = provider.backtest_chain(symbol, spot, day, close_ts, expiry, regime)
        pick = select_option(chain, direction.direction, os_cfg, s, ist_now=ist_close)
        if pick is None:
            continue
        atr_val = ind.atr_arr[i]
        levels = calc_levels(pick, None if np.isnan(atr_val) else float(atr_val), s)
        if levels is None or levels.risk_reward < s.min_risk_reward:
            continue

        entry_px = round((levels.entry_min + levels.entry_max) / 2, 2)
        risk_per_lot = (entry_px - levels.stop_loss) * lot
        lots = int(settings.risk.max_risk_per_trade // risk_per_lot) if risk_per_lot > 0 else 0
        if lots <= 0:
            continue
        qty = lots * lot

        call = pick.row.option_type == "CE"
        exp_dt = datetime.fromisoformat(expiry).replace(hour=15, minute=30, tzinfo=IST)
        status, result, exit_px, exit_ts = "ACTIVE", "OPEN", None, None
        events = [{"ts": close_ts.isoformat(), "event": "GENERATED",
                   "detail": f"{direction.direction} score {direction.display_score}/100 — signal generated at candle close."},
                  {"ts": close_ts.isoformat(), "event": "ACTIVE", "detail": f"Entry filled at ₹{entry_px:.2f}."}]

        # resolve the outcome from later candles only (never used in the decision above)
        validity_cut = close_ts + timedelta(minutes=s.signal_validity_min * 4)
        for k in range(i + 1, min(n, i + 120)):
            k_close = _close_ts(series.ts[k], per)
            t_left = max((exp_dt - to_ist(k_close)).total_seconds(), 60) / (365 * 24 * 3600)
            iv = provider.iv_for_backtest(float(series.c[k]), pick.row.strike, t_left, call, regime)
            _o, h_px, l_px, c_px = option_candles(
                float(series.o[k]), float(series.h[k]), float(series.l[k]), float(series.c[k]),
                pick.row.strike, t_left, iv, call)
            if l_px <= levels.stop_loss and h_px >= levels.target1:
                status, result, exit_px, exit_ts = "STOP_LOSS", "LOSS", levels.stop_loss, k_close
                events.append({"ts": k_close.isoformat(), "event": "STOP_LOSS",
                               "detail": "SL and target both inside one candle — conservative rule treats SL as hit first (36.27)."})
                break
            if l_px <= levels.stop_loss:
                status, result, exit_px, exit_ts = "STOP_LOSS", "LOSS", levels.stop_loss, k_close
                events.append({"ts": k_close.isoformat(), "event": "STOP_LOSS", "detail": f"Option traded down to ₹{levels.stop_loss:.2f}."})
                break
            if h_px >= levels.target2:
                status, result, exit_px, exit_ts = "TARGET2_HIT", "WIN", levels.target2, k_close
                events.append({"ts": k_close.isoformat(), "event": "TARGET2_HIT", "detail": f"Target 2 ₹{levels.target2:.2f} reached."})
                break
            if h_px >= levels.target1:
                status, result, exit_px, exit_ts = "TARGET1_HIT", "WIN", levels.target1, k_close
                events.append({"ts": k_close.isoformat(), "event": "TARGET1_HIT", "detail": f"Target 1 ₹{levels.target1:.2f} reached."})
                break
            if k_close > validity_cut or to_ist(k_close) > exp_dt:
                status, result, exit_px, exit_ts = "EXPIRED", "FLAT", c_px, k_close
                events.append({"ts": k_close.isoformat(), "event": "EXPIRED",
                               "detail": "Signal validity elapsed without SL or target — closed at market."})
                break

        if status == "ACTIVE":
            continue  # unresolved tail — leave it out of history

        snap = {
            "spot": round(spot, 2), "vwap": ind.summary(i).get("vwap"),
            "indicators": ind.summary(i),
            "option": {
                "strike": pick.row.strike, "type": pick.row.option_type, "expiry": expiry,
                "ltp": pick.row.ltp, "bid": pick.row.bid, "ask": pick.row.ask,
                "spread_pct": round((pick.row.ask - pick.row.bid) / max(pick.row.ltp, 1e-9) * 100, 3),
                "volume": pick.row.volume, "oi": pick.row.open_interest,
                "change_in_oi": pick.row.change_in_oi, "iv": pick.row.iv,
                "delta": pick.row.delta, "gamma": pick.row.gamma,
                "theta": pick.row.theta, "vega": pick.row.vega,
                "score": pick.score, "score_breakdown": pick.score_breakdown,
            },
            "fno": {"pcr": summary.pcr, "max_pain": summary.max_pain, "basis": summary.basis,
                    "futures": summary.futures_price, "fut_oi_change": summary.fut_oi_change,
                    "regime": regime},
            "risk": {"capital": settings.risk.capital,
                     "max_risk_per_trade": settings.risk.max_risk_per_trade,
                     "max_qty": qty, "lot_size": lot},
            "session": {"market_status": "OPEN", "session_elapsed": elapsed,
                        "session_mode": "replay", "simulated": True},
            "rejected_candidates": pick.rejected[:8],
            "data_resolution": "5m underlying candles; option premia via Black-Scholes (36.9)",
        }
        sid = str(uuid.uuid4())
        pnl_points = round((exit_px or entry_px) - entry_px, 2)
        doc = {
            "id": sid, "created_at": close_ts, "updated_at": exit_ts or close_ts,
            "symbol": symbol, "spot_at_signal": round(spot, 2),
            "direction": direction.direction, "option_type": pick.row.option_type,
            "strike": pick.row.strike, "expiry": expiry,
            "option_symbol": option_symbol(symbol, pick.row.strike, pick.row.option_type),
            "entry_min": levels.entry_min, "entry_max": levels.entry_max, "entry_price": entry_px,
            "stop_loss": levels.stop_loss, "target1": levels.target1, "target2": levels.target2,
            "risk_reward": levels.risk_reward, "risk_points": levels.risk_points,
            "score": direction.display_score, "strength": strength_label(direction.display_score, s.min_signal_score),
            "status": status, "result": result,
            "exit_price": round(exit_px, 2) if exit_px else None, "exit_time": exit_ts,
            "pnl_points": pnl_points, "option_ltp": round(exit_px or entry_px, 2),
            "max_qty": qty, "filled": True, "paper_executed": True,
            "strategy_name": s.name, "strategy_version": s.version, "day_ist": day,
            "reasons": [f.model_dump() if hasattr(f, "model_dump") else f for f in direction.factors],
            "no_trade_reason": None, "snapshot": snap, "event_log": events,
        }
        await db.signals.insert_one(doc)

        # matching virtual paper position (AC-59: kept separate from the signal record)
        slip = settings.paper.slippage_pct / 100
        entry_eff = round(entry_px * (1 + slip), 2)
        exit_eff = round((exit_px or entry_px) * (1 - slip), 2)
        gross = (exit_eff - entry_eff) * qty
        charges = settings.paper.brokerage_per_order * 2 + (exit_eff + entry_eff) * qty * 0.0005
        await db.paper_positions.insert_one({
            "id": str(uuid.uuid4()), "signal_id": sid, "symbol": symbol,
            "option_symbol": doc["option_symbol"], "option_type": pick.row.option_type,            "strike": pick.row.strike, "expiry": expiry, "side": "BUY", "qty": qty,
            "entry_price": entry_eff, "entry_time": close_ts,
            "stop_loss": levels.stop_loss, "target": levels.target1, "exit_target": 1,
            "status": "CLOSED", "last_price": exit_eff, "exit_price": exit_eff,
            "exit_time": exit_ts, "realized_pnl": round(gross - charges, 2),
            "charges": round(charges, 2), "close_reason": status,
        })

        created += 1
        day_counts[day] = day_counts.get(day, 0) + 1
        cooldown_until = (exit_ts or close_ts) + timedelta(minutes=s.cooldown_min)

        # notification trail: one per signal + one per lifecycle exit (AC-63/64/65)
        await db.notifications.insert_many([
            {"id": str(uuid.uuid4()), "signal_id": sid, "type": "NEW_SIGNAL",
             "title": f"🚨 NEW F&O SIGNAL — {doc['option_symbol']}",
             "body": (f"{direction.direction.title()} setup. Entry ₹{levels.entry_min}–{levels.entry_max}, "
                      f"SL ₹{levels.stop_loss}, T1 ₹{levels.target1}, T2 ₹{levels.target2}. "
                      f"Strength {direction.display_score}/100, R:R 1:{levels.risk_reward}."),
             "ts": close_ts, "read": True},
            {"id": str(uuid.uuid4()), "signal_id": sid, "type": status,
             "title": f"{'✅' if result == 'WIN' else '🛑' if result == 'LOSS' else '⚪'} {status.replace('_', ' ')} — {doc['option_symbol']}",
             "body": f"Exited at ₹{exit_px:.2f} ({pnl_points:+.2f} points on premium). Result: {result}.",
             "ts": exit_ts or close_ts, "read": True},
        ])

    return created


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=25)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    settings_doc = await db.settings.find_one({"_id": "app"})
    settings = AppSettings(**{k: v for k, v in (settings_doc or {}).items() if k != "_id"}) if settings_doc else AppSettings()

    if args.reset:
        await db.signals.delete_many({})
        await db.paper_positions.delete_many({})
        await db.notifications.delete_many({})
        print("cleared signals / paper positions / notifications")

    total = 0
    for symbol in ("NIFTY", "BANKNIFTY"):
        made = await replay(symbol, args.sessions, settings)
        print(f"  {symbol}: {made} signals replayed")
        total += made

    # rebuild the paper account from the realised ledger
    closed = await db.paper_positions.find({"status": "CLOSED"}).to_list(5000)
    realized = sum(p.get("realized_pnl") or 0 for p in closed)
    start = settings.paper.start_capital
    await db.paper_account.update_one({"_id": "main"}, {"$set": {
        "start_capital": start, "cash": round(start + realized, 2),
        "equity": round(start + realized, 2), "realized_pnl": round(realized, 2),
        "peak_equity": round(max(start, start + realized), 2),
        "updated_at": datetime.now(UTC),
    }}, upsert=True)

    print(f"total signals: {total}; realised paper P&L ₹{realized:,.0f}")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
