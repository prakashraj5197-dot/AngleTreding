"""Backtesting engine (§14, §36.10–36.12, §34).

Replays stored historical candles candle-close by candle-close:
  • signal decision at candle close T uses ONLY data ≤ T (precomputed indicator arrays
    are causal by construction; option chains are synthesised deterministically at T);
  • simulated entry at the NEXT candle's open with configurable slippage (36.10/36.28);
  • SL/target monitoring on synthesised option candles; when both SL and target fall
    inside one candle the configurable conservative rule treats SL as hit first (36.27);
  • costs: brokerage per order + exchange charges + slippage — net P&L is what counts
    (36.29);
  • dataset split disclosure: trades are tagged development / validation / out-of-sample
    on a 60/20/20 chronological split (36.32) and a warning is raised below 200 trades
    (36.33).

Deterministic: same dataset + parameters ⇒ identical results (AC-55).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from lib import engine as eng
from lib.db import db
from lib.dates import IST, SESSION_SECONDS, UTC, to_ist
from lib.engine import Series, compute_indicators, evaluate_direction, select_option, calc_levels
from lib.option_math import bs_price, option_candles
from lib.sim_provider import INSTRUMENTS, SimulatedProvider
from models.trading import BacktestRunRequest


def _per_minutes(timeframe: str) -> int:
    return {"1m": 1, "5m": 5, "15m": 15}[timeframe]


def _close_ts(candle_ts: datetime, per: int) -> datetime:
    return candle_ts + timedelta(minutes=per)


def _pick_expiry(provider: SimulatedProvider, symbol: str, ist_dt: datetime,
                 expiry_day_filter_min: int) -> str | None:
    """Same rule as live: nearest expiry, rolled when the expiry-day filter is active."""
    expiries = provider.next_expiries(symbol, ist_dt)
    if not expiries:
        return None
    first = expiries[0]
    elapsed = (ist_dt.hour * 3600 + ist_dt.minute * 60 + ist_dt.second) - 9 * 3600 - 15 * 60
    if first == ist_dt.strftime("%Y-%m-%d") and elapsed > SESSION_SECONDS - expiry_day_filter_min * 60:
        return expiries[1] if len(expiries) > 1 else None
    return first


async def run_backtest(job_id: str) -> None:
    provider = SimulatedProvider()
    job = await db.backtest_jobs.find_one({"id": job_id})
    if not job:
        return
    p = BacktestRunRequest(**job["params"])
    settings = await _load_settings()
    s = settings.strategy
    if p.min_signal_score is not None:
        s.min_signal_score = p.min_signal_score
    if p.min_risk_reward is not None:
        s.min_risk_reward = p.min_risk_reward
    os_cfg = settings.option_selection

    from_dt = datetime.fromisoformat(p.from_date).replace(tzinfo=IST, hour=0, minute=0)
    to_dt = datetime.fromisoformat(p.to_date).replace(tzinfo=IST, hour=23, minute=59)
    docs = await db.candles.find({
        "symbol": p.symbol, "timeframe": p.timeframe,
        "ts": {"$gte": from_dt.astimezone(UTC), "$lte": to_dt.astimezone(UTC)},
    }).sort("ts", 1).to_list(400000)
    if len(docs) < 300:
        await db.backtest_jobs.update_one({"id": job_id}, {"$set": {
            "status": "FAILED",
            "error": f"Only {len(docs)} candles available for {p.symbol} {p.timeframe} in the selected range — minimum 300 required. Seed more history or widen the range.",
            "finished_at": datetime.now(UTC)}})
        return

    series = Series(
        ts=[d["ts"] if d["ts"].tzinfo else d["ts"].replace(tzinfo=UTC) for d in docs],
        o=np.array([d["o"] for d in docs]), h=np.array([d["h"] for d in docs]),
        l=np.array([d["l"] for d in docs]), c=np.array([d["c"] for d in docs]),
        v=np.array([d["v"] for d in docs]),
        session_ids=[(d["ts"].astimezone(IST) if d["ts"].tzinfo else d["ts"].replace(tzinfo=UTC).astimezone(IST)).strftime("%Y-%m-%d") for d in docs],
    )
    ind = compute_indicators(series, s)
    per = _per_minutes(p.timeframe)
    lot = INSTRUMENTS[p.symbol].lot_size

    warmup = max(s.ema_slow + 5, 205, s.breakout_lookback + 1, s.rsi_period + 3)
    slippage = p.slippage_pct / 100
    equity = p.initial_capital
    peak_equity = equity
    max_dd = 0.0
    max_dd_pct = 0.0
    trades: list[dict] = []
    equity_curve: list[dict] = [{"t": series.ts[warmup].isoformat(), "equity": equity}]
    position = None
    cooldown_until: datetime | None = None
    skipped_size = 0
    day_state: dict[str, dict] = {}
    n = len(docs)

    def day_of(ts: datetime) -> str:
        return to_ist(ts).strftime("%Y-%m-%d")

    def day_rec(ts: datetime) -> dict:
        return day_state.setdefault(day_of(ts), {"trades": 0, "pnl": 0.0, "paused": False, "consec": 0})

    for i in range(warmup, n - 1):
        if i % max(1, n // 40) == 0:
            await db.backtest_jobs.update_one({"id": job_id}, {"$set": {"progress": round(i / n * 95, 1)}})

        candle_ts = series.ts[i]
        close_ts = _close_ts(candle_ts, per)
        ist_close = to_ist(close_ts)
        drec = day_rec(candle_ts)

        # ---------------- manage the open position on this candle (data ≤ candle close)
        if position is not None:
            spot_o, spot_h, spot_l, spot_c = series.o[i], series.h[i], series.l[i], series.c[i]
            t_left = (datetime.fromisoformat(position["expiry"]).replace(hour=15, minute=30, tzinfo=IST) - ist_close).total_seconds() / (365 * 24 * 3600)
            iv = provider.iv_for_backtest(float(spot_c), position["strike"], max(t_left, 1e-4), position["side"] == "CE", position["regime"])
            o_px, h_px, l_px, c_px = option_candles(
                float(spot_o), float(spot_h), float(spot_l), float(spot_c),
                position["strike"], max(t_left, 1e-4), iv, position["side"] == "CE")
            sl, tgt = position["sl"], position["target"]
            exit_px = None
            exit_reason = None
            if l_px <= sl and h_px >= tgt and p.conservative_same_candle_rule:
                exit_px, exit_reason = sl * (1 - slippage), "STOP_LOSS (conservative same-candle rule — 36.27)"
            elif l_px <= sl:
                exit_px, exit_reason = sl * (1 - slippage), "STOP_LOSS"
            elif h_px >= tgt:
                exit_px, exit_reason = tgt * (1 - slippage), f"TARGET{position['exit_target']}_HIT"
            elif ist_close.hour == 15 and ist_close.minute >= 15:
                exit_px, exit_reason = c_px * (1 - slippage), "SQUARE_OFF"
            elif t_left <= 0:
                exit_px, exit_reason = max(c_px, 0.05), "OPTION_EXPIRED"
            if exit_px is not None:
                gross = (exit_px - position["entry"]) * position["qty"]
                costs = p.brokerage_per_order * 2 + (exit_px + position["entry"]) * position["qty"] * p.charges_pct / 100
                net = gross - costs
                equity += net
                peak_equity = max(peak_equity, equity)
                dd = peak_equity - equity
                if equity > 0 and dd / peak_equity > max_dd_pct:
                    max_dd_pct = dd / peak_equity * 100
                max_dd = max(max_dd, dd)
                risk_amt = (position["entry"] - position["sl"]) * position["qty"]
                trades.append({
                    "n": len(trades) + 1, "entry_ts": position["entry_ts"], "exit_ts": close_ts,
                    "side": position["side"], "strike": position["strike"], "expiry": position["expiry"],
                    "qty": position["qty"], "entry_price": round(position["entry"], 2),
                    "exit_price": round(exit_px, 2), "sl": round(position["sl"], 2),
                    "target": round(position["target"], 2), "pnl": round(net, 2),
                    "gross_pnl": round(gross, 2), "costs": round(costs, 2),
                    "pnl_pct": round((exit_px / position["entry"] - 1) * 100, 2),
                    "r_multiple": round(net / risk_amt, 2) if risk_amt > 0 else 0.0,
                    "result": "WIN" if net > 0 else ("LOSS" if net < 0 else "FLAT"),
                    "exit_reason": exit_reason, "regime": position["regime"],
                    "segment": _segment(day_of(position["entry_ts"]), p),
                })
                drec["trades"] += 1
                drec["pnl"] += net
                drec["consec"] = drec["consec"] + 1 if net < 0 else 0
                if equity_curve and (len(trades) == 1 or len(equity_curve) < 600):
                    equity_curve.append({"t": close_ts.isoformat(), "equity": round(equity, 2)})
                cooldown_until = close_ts + timedelta(minutes=15)
                position = None

        # ---------------- signal evaluation at this candle close (data ≤ close)
        if position is not None or drec["paused"]:
            continue
        if cooldown_until and close_ts < cooldown_until:
            continue
        elapsed = (ist_close.hour * 3600 + ist_close.minute * 60) - 9 * 3600 - 15 * 60
        if elapsed < s.opening_filter_min * 60 or elapsed > SESSION_SECONDS - s.closing_filter_min * 60:
            continue
        expiry = _pick_expiry(provider, p.symbol, ist_close, s.expiry_day_filter_min)
        if not expiry:
            continue
        regime = provider._regime_for(p.symbol, day_of(candle_ts))
        # cheap aggregates first — a fully priced chain is built only if direction qualifies
        summary = provider.chain_summary(p.symbol, float(series.c[i]), day_of(candle_ts), close_ts, expiry, regime)
        direction = evaluate_direction(series, ind, _chain_stub(summary), None, s, idx=i)
        if direction.direction not in ("BULLISH", "BEARISH"):
            continue
        # backtest-local risk gates
        if drec["consec"] >= s_max_consec(settings):
            drec["paused"] = True
            continue
        if drec["pnl"] <= -_daily_limit(settings, p):
            drec["paused"] = True
            continue
        if drec["trades"] >= s.max_signals_per_symbol_day:
            continue
        chain = provider.backtest_chain(p.symbol, float(series.c[i]), day_of(candle_ts), close_ts, expiry, regime)
        pick = select_option(_chain_stub(chain), direction.direction, os_cfg, s, ist_now=ist_close)
        if pick is None:
            continue
        atr_val = ind.atr_arr[i]
        levels = calc_levels(pick, None if np.isnan(atr_val) else float(atr_val), s)
        if levels is None or levels.risk_reward < s.min_risk_reward:
            continue
        # entry at the next candle's open with slippage (36.10 / 36.28)
        nxt_spot = float(series.o[i + 1])
        t_left = (datetime.fromisoformat(expiry).replace(hour=15, minute=30, tzinfo=IST) - to_ist(_close_ts(series.ts[i + 1], per))).total_seconds() / (365 * 24 * 3600)
        iv_n = provider.iv_for_backtest(nxt_spot, pick.row.strike, max(t_left, 1e-4), pick.row.option_type == "CE", regime)
        entry_px = float(bs_price(
            nxt_spot, pick.row.strike, max(t_left, 1e-4), iv_n, pick.row.option_type == "CE")) * (1 + slippage)
        risk_amt = min(settings.risk.max_risk_per_trade, equity * p.risk_per_trade_pct / 100)
        risk_per_lot = (entry_px - levels.stop_loss) * lot
        lots = int(risk_amt // risk_per_lot) if risk_per_lot > 0 else 0
        if lots <= 0 or entry_px <= levels.stop_loss:
            skipped_size += 1
            continue
        position = {
            "entry_ts": close_ts, "entry": entry_px, "sl": levels.stop_loss,
            "target": levels.target1, "exit_target": 1, "qty": lots * lot,
            "side": pick.row.option_type, "strike": pick.row.strike, "expiry": expiry,
            "regime": regime,
        }

    if position is not None:  # force-close any open position at dataset end
        i = n - 1
        spot_c = float(series.c[i])
        close_ts = _close_ts(series.ts[i], per)
        t_left = (datetime.fromisoformat(position["expiry"]).replace(hour=15, minute=30, tzinfo=IST) - to_ist(close_ts)).total_seconds() / (365 * 24 * 3600)
        iv = provider.iv_for_backtest(spot_c, position["strike"], max(t_left, 1e-4), position["side"] == "CE", position["regime"])
        exit_px = float(bs_price(spot_c, position["strike"], max(t_left, 1e-4), iv, position["side"] == "CE")) * (1 - slippage)
        gross = (exit_px - position["entry"]) * position["qty"]
        costs = p.brokerage_per_order * 2 + (exit_px + position["entry"]) * position["qty"] * p.charges_pct / 100
        equity += gross - costs
        trades.append({
            "n": len(trades) + 1, "entry_ts": position["entry_ts"], "exit_ts": close_ts,
            "side": position["side"], "strike": position["strike"], "expiry": position["expiry"],
            "qty": position["qty"], "entry_price": round(position["entry"], 2),
            "exit_price": round(exit_px, 2), "sl": round(position["sl"], 2),
            "target": round(position["target"], 2), "pnl": round(gross - costs, 2),
            "gross_pnl": round(gross, 2), "costs": round(costs, 2),
            "pnl_pct": round((exit_px / position["entry"] - 1) * 100, 2),
            "r_multiple": 0.0, "result": "WIN" if gross - costs > 0 else "LOSS",
            "exit_reason": "BACKTEST_END", "regime": position["regime"],
            "segment": _segment(day_of(position["entry_ts"]), p),
        })
        equity_curve.append({"t": close_ts.isoformat(), "equity": round(equity, 2)})

    metrics = _metrics(trades, equity_curve, max_dd, max_dd_pct, p.initial_capital)
    warnings: list[str] = []
    if len(trades) < 200:
        warnings.append(f"Sample size {len(trades)} is below the 200-trade minimum — treat these statistics as indicative only (36.33).")
    if skipped_size:
        warnings.append(
            f"{skipped_size} qualifying setup(s) were skipped because the risk budget "
            f"(min of ₹{settings.risk.max_risk_per_trade:,.0f} per trade and {p.risk_per_trade_pct:.2f}% of equity) "
            f"could not fund one lot of {lot} — raise capital/risk per trade to trade these setups.")
    warnings.append(f"Option fills are synthesised from {p.timeframe} underlying candles via Black-Scholes — the backtest does NOT assume tick-level execution accuracy (36.9).")
    warnings.append(f"Costs modelled: slippage {p.slippage_pct:.2f}% per fill, brokerage ₹{p.brokerage_per_order:.0f} per order, exchange/regulatory charges {p.charges_pct:.2f}% of turnover (36.28/36.29).")
    if p.conservative_same_candle_rule:
        warnings.append("Conservative execution: when SL and target both fall inside one candle, SL is treated as hit first (36.27).")

    # persist trades (capped) + finalise job
    trade_docs = [dict(t, job_id=job_id) for t in trades[:3000]]
    if trade_docs:
        await db.backtest_trades.insert_many(trade_docs)
    stored = len(trade_docs)
    if len(trades) > stored:
        warnings.append(f"Trade log truncated to the first {stored} of {len(trades)} trades.")
    dataset_info = {
        "candles": n, "timeframe": p.timeframe, "symbol": p.symbol,
        "from": p.from_date, "to": p.to_date,
        "split_60_20_20": _split_dates(p),
        "assumptions": {"slippage_pct": p.slippage_pct, "brokerage_per_order": p.brokerage_per_order,
                        "charges_pct": p.charges_pct, "risk_free_rate": 0.065,
                        "conservative_same_candle_rule": p.conservative_same_candle_rule},
        "strategy": {"name": s.name, "version": s.version, "params": s.model_dump()},
    }
    await db.backtest_jobs.update_one({"id": job_id}, {"$set": {
        "status": "COMPLETED", "progress": 100.0, "finished_at": datetime.now(UTC),
        "metrics": metrics, "equity_curve": equity_curve[-600:],
        "trades_count": len(trades), "warnings": warnings, "dataset_info": dataset_info,
    }})


def s_max_consec(settings) -> int:
    return settings.risk.consecutive_loss_limit


def _daily_limit(settings, p: BacktestRunRequest) -> float:
    return p.initial_capital * p.daily_loss_limit_pct / 100


def _segment(day_str: str, p: BacktestRunRequest) -> str:
    d0 = datetime.fromisoformat(p.from_date).date()
    d1 = datetime.fromisoformat(p.to_date).date()
    span = (d1 - d0).days or 1
    d = datetime.fromisoformat(day_str).date()
    if d < d0 + timedelta(days=span * 0.6):
        return "development"
    if d < d0 + timedelta(days=span * 0.8):
        return "validation"
    return "out_of_sample"


def _split_dates(p: BacktestRunRequest) -> dict:
    d0 = datetime.fromisoformat(p.from_date).date()
    d1 = datetime.fromisoformat(p.to_date).date()
    span = (d1 - d0).days
    return {
        "development": [p.from_date, (d0 + timedelta(days=span * 0.6)).isoformat()],
        "validation": [(d0 + timedelta(days=span * 0.6)).isoformat(), (d0 + timedelta(days=span * 0.8)).isoformat()],
        "out_of_sample": [(d0 + timedelta(days=span * 0.8)).isoformat(), p.to_date],
    }


class _ChainView:
    """Adapter exposing the fields evaluate_direction/select_option read from a ChainOut."""

    def __init__(self, raw) -> None:
        self.underlying = raw.underlying
        self.spot = raw.spot
        self.atm_strike = raw.atm_strike
        self.ts = raw.ts
        self.pcr = raw.pcr
        self.max_pain = raw.max_pain
        self.futures_price = raw.futures_price
        self.basis = raw.basis
        self.fut_oi_change = raw.fut_oi_change
        self.regime = raw.regime
        self.expiries = []
        self.rows = raw.rows


def _chain_stub(raw):
    return _ChainView(raw)


def _metrics(trades: list[dict], equity_curve: list[dict], max_dd: float,
             max_dd_pct: float, initial_capital: float) -> dict:
    if not trades:
        return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "gross_pnl": 0.0, "total_costs": 0.0, "net_pnl": 0.0,
                "avg_profit": 0.0, "avg_loss": 0.0, "profit_factor": 0.0,
                "max_drawdown": 0.0, "max_drawdown_pct": 0.0, "avg_r": 0.0,
                "largest_win": 0.0, "largest_loss": 0.0,
                "call_trades": 0, "put_trades": 0, "call_pnl": 0.0, "put_pnl": 0.0,
                "monthly": [], "regime_stats": [], "segment_stats": []}
    pnls = [t["pnl"] for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    gross = sum(t.get("gross_pnl", t["pnl"]) for t in trades)
    costs = sum(t.get("costs", 0.0) for t in trades)
    monthly: dict[str, dict] = {}
    for t in trades:
        m = t["exit_ts"].astimezone(IST).strftime("%Y-%m") if t["exit_ts"].tzinfo else t["exit_ts"].strftime("%Y-%m")
        rec = monthly.setdefault(m, {"month": m, "trades": 0, "wins": 0, "pnl": 0.0})
        rec["trades"] += 1
        rec["wins"] += 1 if t["pnl"] > 0 else 0
        rec["pnl"] = round(rec["pnl"] + t["pnl"], 2)
    for rec in monthly.values():
        rec["win_rate"] = round(rec["wins"] / rec["trades"] * 100, 1)

    def group(key: str) -> list[dict]:
        buckets: dict[str, dict] = {}
        for t in trades:
            k = t.get(key) or "unknown"
            rec = buckets.setdefault(k, {"regime" if key == "regime" else ("segment" if key == "segment" else "side"): k,
                                         "trades": 0, "wins": 0, "pnl": 0.0})
            rec["trades"] += 1
            rec["wins"] += 1 if t["pnl"] > 0 else 0
            rec["pnl"] = round(rec["pnl"] + t["pnl"], 2)
        for rec in buckets.values():
            rec["win_rate"] = round(rec["wins"] / rec["trades"] * 100, 1)
        return list(buckets.values())

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "gross_pnl": round(gross, 2),
        "total_costs": round(costs, 2),
        "net_pnl": round(sum(pnls), 2),
        "avg_profit": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else (999.0 if wins else 0.0),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "avg_r": round(float(np.mean([t.get("r_multiple", 0.0) for t in trades])), 3),
        "largest_win": round(max(pnls), 2),
        "largest_loss": round(min(pnls), 2),
        "call_trades": sum(1 for t in trades if t["side"] == "CE"),
        "put_trades": sum(1 for t in trades if t["side"] == "PE"),
        "call_pnl": round(sum(t["pnl"] for t in trades if t["side"] == "CE"), 2),
        "put_pnl": round(sum(t["pnl"] for t in trades if t["side"] == "PE"), 2),
        "monthly": sorted(monthly.values(), key=lambda r: r["month"]),
        "regime_stats": group("regime"),
        "segment_stats": group("segment"),
    }


async def _load_settings():
    from lib.signal_engine import get_settings

    return await get_settings()
