"""Signal engine — orchestrates freshness checks, the direction/option/level engines,
risk gates, signal persistence, lifecycle monitoring, notifications and paper trading.

Every generated signal is fully auditable (§23): the exact market snapshot, indicator
values, option-chain state, strategy version, score and decision are stored with the
signal, so it stays reproducible after live conditions change (AC-07).
"""

from __future__ import annotations

import logging
import time as _time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from lib import engine
from lib.db import db
from lib.dates import IST, SESSION_SECONDS, UTC, ist_date, ist_midnight_utc, now_utc
from lib.engine import Series, compute_indicators, evaluate_direction, select_option, calc_levels, strength_label
from lib.risk import ACTIVE_STATUSES, risk_verdict
from lib.broker_angelone import ProviderUnavailable
from lib.sim_provider import SimulatedProvider
from models.trading import (
    AppSettings,
    ChainOut,
    EngineState,
    OptionRowOut,
    Signal,
)

FEED_SYMBOLS = ["NIFTY", "BANKNIFTY"]
ANALYSIS_SYMBOLS = ["NIFTY", "BANKNIFTY"]

logger = logging.getLogger("quantpulse.engine")

_provider = None  # kept for backwards compatibility; use get_provider()
_active_provider_name = "simulated"


def get_provider():
    """The market-data vendor currently selected in Settings.

    Returns the SIMULATOR or the Angel One SmartAPI adapter — both satisfy the same
    surface, so no engine code knows the difference. When the live vendor is selected but
    failing, its methods raise ProviderUnavailable and callers fail safe (DATA STALE,
    signal generation paused) rather than substituting simulated prices.
    """
    from lib import provider_registry

    return provider_registry.resolve(_active_provider_name)


# ---------------------------------------------------------------- settings

_SETTINGS_CACHE: dict = {"doc": None, "ts": 0.0}


async def get_settings(force: bool = False) -> AppSettings:
    if not force and _SETTINGS_CACHE["doc"] is not None and _time.monotonic() - _SETTINGS_CACHE["ts"] < 5:
        return _SETTINGS_CACHE["doc"]
    raw = await db.settings.find_one({"_id": "app"})
    doc = AppSettings(**(raw or {})) if raw else AppSettings()
    doc.data.session_mode = doc.data.session_mode or "always_on"
    global _active_provider_name
    _active_provider_name = doc.data.provider
    prov = get_provider()
    # the freeze / session-mode toggles are demo controls: they only apply to the simulator,
    # a real exchange feed's clock and staleness come from the vendor itself
    if getattr(prov, "name", "simulated") == "simulated":
        prov.set_session_mode(doc.data.session_mode)
        prov.force_stale = doc.data.force_stale
        if doc.data.force_stale and prov.frozen_at is None:
            prov.freeze_feed()
        elif not doc.data.force_stale:
            prov.unfreeze_feed()
    _SETTINGS_CACHE.update(doc=doc, ts=_time.monotonic())
    return doc


async def save_settings(new: AppSettings) -> AppSettings:
    new.updated_at = now_utc()
    await db.settings.replace_one({"_id": "app"}, new.model_dump(), upsert=True)
    _SETTINGS_CACHE.update(doc=new, ts=_time.monotonic())
    return new


# ---------------------------------------------------------------- data loading

async def anchor_close(symbol: str) -> float | None:
    """Session anchor: the close of the last stored candle for the symbol."""
    doc = await db.candles.find_one({"symbol": symbol}, sort=[("ts", -1)])
    return doc["c"] if doc else None


async def sim_anchor(symbol: str, day_key: str) -> float:
    """Anchor fixed per simulated session (stored in sim_state) so the day path is stable."""
    state = await db.sim_state.find_one({"symbol": symbol})
    if state and state.get("day_key") == day_key and state.get("anchor_close"):
        return state["anchor_close"]
    anchor = await anchor_close(symbol) or get_provider().live_anchor(symbol, None)
    await db.sim_state.replace_one(
        {"symbol": symbol},
        {"symbol": symbol, "day_key": day_key, "anchor_close": anchor, "updated_at": now_utc()},
        upsert=True)
    return anchor


async def load_series(symbol: str, timeframe: str, limit: int, quote=None) -> Series:
    """Stored candles merged with the live provider day (fresh 1m → 5m/15m aggregates).

    Provider candles win on ts collisions (same minute re-ingested = update, AC-03).
    """
    per = {"1m": 1, "5m": 5, "15m": 15}[timeframe]
    stored = await db.candles.find({"symbol": symbol, "timeframe": timeframe}) \
        .sort("ts", -1).limit(limit + 500).to_list(limit + 500)
    # motor hands back NAIVE datetimes (BSON stores UTC) — normalise before any compare
    by_ts: dict = {}
    for d in stored:
        ts = d["ts"] if d["ts"].tzinfo else d["ts"].replace(tzinfo=UTC)
        d["ts"] = ts
        by_ts[ts] = d
    if quote is None or quote.market_status == "OPEN":
        anchor = await sim_anchor(symbol, get_provider()._clock()[0])
        today_1m = get_provider().today_candles(symbol, anchor, "1m")
        today_tf = today_1m if per == 1 else get_provider()._aggregate(today_1m, per)
        for d in today_tf:
            ts = d["ts"] if d["ts"].tzinfo else d["ts"].replace(tzinfo=UTC)
            d["ts"] = ts
            by_ts[ts] = d
    rows = sorted(by_ts.values(), key=lambda d: d["ts"])[-limit:]
    ts = [r["ts"] for r in rows]
    sids = [t.astimezone(IST).strftime("%Y-%m-%d") for t in ts]
    return Series(
        ts=ts,
        o=np.array([r["o"] for r in rows]),
        h=np.array([r["h"] for r in rows]),
        l=np.array([r["l"] for r in rows]),
        c=np.array([r["c"] for r in rows]),
        v=np.array([r["v"] for r in rows]),
        session_ids=sids,
    )


# ---------------------------------------------------------------- notifications

async def notify(ntype: str, title: str, body: str, signal_id: str | None = None) -> None:
    settings = await get_settings()
    if not settings.notifications.enabled:
        return
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()), "ts": now_utc(), "type": ntype,
        "title": title, "body": body, "signal_id": signal_id, "read": False,
    })


# ---------------------------------------------------------------- evaluation

async def evaluate_symbol(symbol: str, settings: AppSettings | None = None) -> EngineState:
    """One evaluation cycle for `symbol`. Stores engine state; may create a signal."""
    s = settings or await get_settings()
    t0 = _time.perf_counter()
    provider = get_provider()
    live = getattr(provider, "name", "simulated") != "simulated"
    try:
        status = provider.get_status()
        anchor = await sim_anchor(symbol, provider._clock()[0]) if not live else None
        quote = provider.get_quote(symbol, anchor)
    except ProviderUnavailable as exc:
        # AC-74: the vendor is down / unauthenticated → show the real state and stop.
        # We never fall back to simulated prices while claiming to be live.
        state = {
            "symbol": symbol, "ts": now_utc(), "market_status": "CLOSED",
            "stale": True, "direction": "NO_TRADE", "score": 0.0, "display_score": 0,
            "factors": [], "reasons": [], "indicators": {},
            "evaluation_ms": int((_time.perf_counter() - t0) * 1000),
            "no_trade_reason": f"🔴 DATA FEED DISCONNECTED — SIGNAL GENERATION PAUSED. {exc}",
        }
        await db.engine_state.replace_one({"symbol": symbol}, _clean(state), upsert=True)
        logger.error("provider unavailable for %s: %s", symbol, exc)
        return EngineState(**_clean(state))

    # freshness (36.3 / AC-02 / AC-39)
    now = now_utc()
    price_age = (now - quote.ts).total_seconds()
    forced = bool(getattr(provider, "force_stale", False))
    stale = forced or (price_age > s.data.price_fresh_s)

    state = {
        "symbol": symbol, "ts": now, "market_status": status.status,
        "stale": stale, "direction": "NO_TRADE", "score": 0.0, "display_score": 0,
        "factors": [], "reasons": [], "no_trade_reason": None,
        "indicators": {}, "evaluation_ms": 0,
    }

    async def finish(dir_state: dict | None = None):
        state["evaluation_ms"] = int((_time.perf_counter() - t0) * 1000)
        if dir_state:
            state.update(dir_state)
        await db.engine_state.replace_one({"symbol": symbol}, _clean(state), upsert=True)
        return EngineState(**_clean(state))

    if status.status != "OPEN":
        return await finish({"no_trade_reason": "MARKET CLOSED — live signal generation paused."})
    if stale and s.data.stale_block_signals:
        return await finish({"no_trade_reason": "🔴 DATA STALE — SIGNAL GENERATION PAUSED (price feed age "
                                          f"{price_age:.0f}s exceeds the {s.data.price_fresh_s}s freshness threshold)."
                       if not forced else "🔴 DATA STALE — SIGNAL GENERATION PAUSED (provider feed frozen — forced-stale simulation active)."})

    elapsed = quote.session_elapsed
    expiries = provider.next_expiries(symbol)
    is_expiry_day = bool(expiries) and expiries[0] == ist_date()
    if elapsed < s.strategy.opening_filter_min * 60:
        return await finish({"no_trade_reason": f"Opening filter — no signals in the first {s.strategy.opening_filter_min} minutes of the session (36.16)."})
    if elapsed > SESSION_SECONDS - s.strategy.closing_filter_min * 60:
        return await finish({"no_trade_reason": f"Closing filter — no new entries in the final {s.strategy.closing_filter_min} minutes (36.17)."})
    if is_expiry_day and elapsed > SESSION_SECONDS - s.strategy.expiry_day_filter_min * 60:
        return await finish({"no_trade_reason": "⚠️ EXPIRY-DAY RISK FILTER ACTIVE — no new option buys in the final "
                                          f"{s.strategy.expiry_day_filter_min} minutes on expiry day (36.18)."})

    series = await load_series(symbol, s.strategy.signal_timeframe, 400, quote)
    if series.c.size < max(60, s.strategy.ema_slow + 5):
        return await finish({"no_trade_reason": "Insufficient candle history for indicator warm-up — data marked unavailable (AC-72)."})
    ind = compute_indicators(series, s.strategy)
    chain_raw = provider.build_chain(symbol, quote)
    chain = ChainOut(
        underlying=chain_raw.underlying, spot=chain_raw.spot, atm_strike=chain_raw.atm_strike,
        ts=chain_raw.ts, pcr=chain_raw.pcr, max_pain=chain_raw.max_pain,
        futures_price=chain_raw.futures_price, basis=chain_raw.basis,
        fut_oi_change=chain_raw.fut_oi_change, regime=chain_raw.regime,
        expiries=provider.next_expiries(symbol),
        rows=[OptionRowOut(**r.__dict__) for r in chain_raw.rows],
    )
    direction = evaluate_direction(series, ind, chain, quote, s.strategy)
    base = {
        "direction": direction.direction, "score": direction.score,
        "display_score": direction.display_score,
        "factors": [f.model_dump() for f in direction.factors],
        "reasons": direction.reasons,
        "indicators": {**ind.summary(series.c.size - 1),
                       "spot": quote.ltp, "vwap_quote": quote.vwap,
                       "pcr": chain.pcr, "max_pain": chain.max_pain,
                       "basis": chain.basis, "futures": chain.futures_price,
                       "fut_oi_change": chain.fut_oi_change, "regime": chain.regime},
    }
    if direction.direction in ("SIDEWAYS", "NO_TRADE"):
        base["no_trade_reason"] = direction.no_trade_reason
        return await finish(base)

    # risk gates (§17)
    verdict = await risk_verdict(symbol, s.risk, s.strategy.name)
    cooldown_cut = False
    if verdict.last_signal_at is not None:
        created = verdict.last_signal_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if now_utc() - created < timedelta(minutes=s.strategy.cooldown_min):
            cooldown_cut = True
    if verdict.allowed is False or cooldown_cut:
        reason = "; ".join(verdict.reasons) if verdict.reasons else ""
        if cooldown_cut:
            reason = f"Signal cooldown active ({s.strategy.cooldown_min} min per underlying per strategy — 36.13)."
        base["no_trade_reason"] = reason or "Risk management blocked this setup."
        return await finish(base)

    # re-entry rule (36.14): at most one re-entry per underlying per day after a stop-loss
    sl_today = await db.signals.count_documents(
        {"day_ist": ist_date(), "symbol": symbol, "strategy_name": s.strategy.name,
         "result": "LOSS"})
    if sl_today >= s.strategy.max_reentries_per_day + 1:
        base["no_trade_reason"] = ("Re-entry limit reached — maximum "
                                   f"{s.strategy.max_reentries_per_day} re-entry per underlying per day after a stop-loss (36.14).")
        return await finish(base)

    # option selection (§8)
    pick = select_option(chain, direction.direction, s.option_selection, s.strategy)
    if pick is None:
        base["no_trade_reason"] = "No liquid option meets the selection criteria (liquidity/spread/premium/minimum score)."
        return await finish(base)

    atr_val = ind.atr_arr[series.c.size - 1]
    levels = calc_levels(pick, None if np.isnan(atr_val) else float(atr_val), s.strategy)
    if levels is None:
        base["no_trade_reason"] = "A valid stop-loss could not be calculated — signal rejected (AC-20)."
        return await finish(base)
    if levels.risk_reward < s.strategy.min_risk_reward:
        base["no_trade_reason"] = (f"Risk/reward 1:{levels.risk_reward:.2f} is below the configured minimum "
                                   f"1:{s.strategy.min_risk_reward:.2f} (AC-23).")
        return await finish(base)

    # ---- persist signal (AC-24..27, §22/§23) --------------------------------
    lot = _lot_size(symbol)
    risk_per_lot = (levels.entry_max - levels.stop_loss) * lot
    max_qty = max(0, int(s.risk.max_risk_per_trade // risk_per_lot)) * lot if risk_per_lot > 0 else 0
    now_dt = now_utc()
    sig = Signal(
        id=str(uuid.uuid4()), created_at=now_dt, updated_at=now_dt,
        symbol=symbol, spot_at_signal=quote.ltp, direction=direction.direction,
        option_type=pick.row.option_type, strike=pick.row.strike, expiry=pick.row.expiry,
        option_symbol=engine.option_symbol(symbol, pick.row.strike, pick.row.option_type),
        entry_min=levels.entry_min, entry_max=levels.entry_max, stop_loss=levels.stop_loss,
        target1=levels.target1, target2=levels.target2, risk_reward=levels.risk_reward,
        risk_points=levels.risk_points, score=direction.display_score,
        strength=strength_label(direction.display_score, s.strategy.min_signal_score), status="ACTIVE", result="OPEN",
        option_ltp=pick.row.ltp, max_qty=max_qty,
        strategy_name=s.strategy.name, strategy_version=s.strategy.version,
        reasons=direction.factors,
        day_ist=ist_date(),
        snapshot={
            "spot": quote.ltp, "vwap": quote.vwap, "indicators": state["indicators"],
            "option": {
                "strike": pick.row.strike, "type": pick.row.option_type, "expiry": pick.row.expiry,
                "ltp": pick.row.ltp, "bid": pick.row.bid, "ask": pick.row.ask,
                "spread_pct": round((pick.row.ask - pick.row.bid) / max(pick.row.ltp, 1e-9) * 100, 3),
                "volume": pick.row.volume, "oi": pick.row.open_interest,
                "change_in_oi": pick.row.change_in_oi, "iv": pick.row.iv,
                "delta": pick.row.delta, "gamma": pick.row.gamma,
                "theta": pick.row.theta, "vega": pick.row.vega,
                "score": pick.score, "score_breakdown": pick.score_breakdown,
            },
            "fno": {"pcr": chain.pcr, "max_pain": chain.max_pain, "basis": chain.basis,
                    "futures": chain.futures_price, "fut_oi_change": chain.fut_oi_change,
                    "regime": chain.regime},
            "risk": {"capital": s.risk.capital, "max_risk_per_trade": s.risk.max_risk_per_trade,
                     "max_qty": max_qty, "lot_size": lot,
                     "trades_today": verdict.trades_today, "consecutive_losses": verdict.consecutive_losses},
            "session": {"market_status": status.status, "session_elapsed": elapsed,
                        "session_mode": status.session_mode, "simulated": True},
            "rejected_candidates": pick.rejected[:8],
        },
        event_log=[{"ts": now_dt, "event": "GENERATED", "detail": "Signal generated by strategy evaluation cycle."}],
    )
    await db.signals.insert_one(sig.model_dump())
    await notify("NEW_SIGNAL", f"🚨 NEW F&O SIGNAL — {sig.option_symbol}",
                 f"{direction.direction.title()} setup. Entry ₹{levels.entry_min}–{levels.entry_max}, "
                 f"SL ₹{levels.stop_loss}, T1 ₹{levels.target1}, T2 ₹{levels.target2}. "
                 f"Strength {direction.display_score}/100, R:R 1:{levels.risk_reward}. "
                 f"Reasons: {'; '.join(direction.reasons[:4])}", sig.id)
    base["direction"] = direction.direction
    base["signal_id"] = sig.id
    return finish(base)


def _lot_size(symbol: str) -> int:
    from lib.sim_provider import INSTRUMENTS

    return INSTRUMENTS[symbol].lot_size if symbol in INSTRUMENTS else 1


def _clean(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _clean(v)
        elif isinstance(v, (list, tuple)):
            out[k] = [_clean(x) if isinstance(x, dict) else x for x in v]
        elif v is not None and not (isinstance(v, float) and np.isnan(v)):
            out[k] = v
    return out


# ---------------------------------------------------------------- lifecycle monitoring

async def monitor_once() -> None:
    """Tick-level tracking of ACTIVE signals + paper positions (§36.12: monitoring only)."""
    s = await get_settings()
    provider = get_provider()
    status = provider.get_status()
    now = now_utc()
    valid_statuses = ACTIVE_STATUSES + ["TARGET1_HIT"]

    signals = [doc async for doc in db.signals.find({"status": {"$in": valid_statuses}})]
    if signals:
        chain_cache: dict[str, ChainOut] = {}
        for doc in signals:
            try:
                await _monitor_signal(doc, provider, s, status, now, chain_cache)
            except ProviderUnavailable as exc:
                # feed problem, not a signal problem — leave the signal ACTIVE and retry
                logger.error("monitor paused, provider unavailable: %s", exc)
                return
            except Exception as exc:  # never let one bad tick kill the monitor
                await db.signals.update_one({"id": doc["id"]}, {"$set": {
                    "status": "DATA_ERROR", "updated_at": now,
                    "no_trade_reason": f"monitor error: {exc}"}})

    try:
        await _monitor_paper(s, provider, status, now)
    except ProviderUnavailable as exc:
        logger.error("paper monitor paused, provider unavailable: %s", exc)
        return

    # periodic option-chain snapshot storage (AC-06)
    if status.status == "OPEN" and not getattr(provider, "force_stale", False):
        minute = int(status.session_elapsed // 60)
        if minute % 15 == 0:
            existing = await db.option_chain_snapshots.find_one(
                {"underlying": "NIFTY"}, sort=[("ts", -1)])
            if not existing or (now - (existing["ts"] if existing["ts"].tzinfo else existing["ts"].replace(tzinfo=UTC))).total_seconds() > 14 * 60:
                try:
                    anchor = await sim_anchor("NIFTY", provider._clock()[0])
                    quote = provider.get_quote("NIFTY", anchor)
                    chain = provider.build_chain("NIFTY", quote)
                except ProviderUnavailable as exc:
                    logger.error("chain snapshot skipped, provider unavailable: %s", exc)
                    return
                await db.option_chain_snapshots.insert_one({
                    "ts": quote.ts, "underlying": "NIFTY", "spot": chain.spot,
                    "expiry": chain.rows[0].expiry if chain.rows else None,
                    "pcr": chain.pcr, "max_pain": chain.max_pain, "regime": chain.regime,
                    "rows": [r.__dict__ for r in chain.rows],
                })


async def _option_row(provider: SimulatedProvider, symbol: str, doc: dict,
                      chain_cache: dict) -> OptionRowOut | None:
    if symbol not in chain_cache:
        anchor = await sim_anchor(symbol, provider._clock()[0])
        quote = provider.get_quote(symbol, anchor)
        raw = provider.build_chain(symbol, quote)
        chain_cache[symbol] = ChainOut(
            underlying=raw.underlying, spot=raw.spot, atm_strike=raw.atm_strike, ts=raw.ts,
            pcr=raw.pcr, max_pain=raw.max_pain, futures_price=raw.futures_price,
            basis=raw.basis, fut_oi_change=raw.fut_oi_change, regime=raw.regime,
            expiries=provider.next_expiries(symbol),
            rows=[OptionRowOut(**r.__dict__) for r in raw.rows])
    chain = chain_cache[symbol]
    for row in chain.rows:
        if row.expiry == doc["expiry"] and row.strike == doc["strike"] \
                and row.option_type == doc["option_type"]:
            return row
    return None


async def _monitor_signal(doc, provider, s: AppSettings, status, now, chain_cache) -> None:
    row = await _option_row(provider, doc["symbol"], doc, chain_cache)
    ltp = row.ltp if row else doc.get("option_ltp", 0.0)
    updates: dict = {"option_ltp": ltp, "updated_at": now}
    events = list(doc.get("event_log", []))
    sig_status = doc["status"]
    filled = doc.get("filled", False)
    created = doc["created_at"] if doc["created_at"].tzinfo else doc["created_at"].replace(tzinfo=UTC)

    def add_event(evt: str, detail: str):
        events.append({"ts": now, "event": evt, "detail": detail})
        updates["event_log"] = events

    if status.status != "OPEN":  # session square-off handled at close time below
        pass

    if not filled:
        if ltp and doc["entry_min"] <= ltp <= doc["entry_max"]:
            updates["filled"] = True
            updates["entry_price"] = ltp
            add_event("ENTRY_FILLED", f"Entry filled at ₹{ltp:.2f} (inside ₹{doc['entry_min']}–{doc['entry_max']}).")
        elif now - created > timedelta(minutes=s.strategy.signal_validity_min):
            updates["status"] = "EXPIRED"
            updates["result"] = "MISSED_ENTRY"
            updates["exit_price"] = ltp or None
            updates["exit_time"] = now
            add_event("EXPIRED", f"Price never traded inside the entry range within {s.strategy.signal_validity_min} min — signal expired (36.30/36.31).")
            await notify("EXPIRED", f"⏱️ SIGNAL EXPIRED — {doc['option_symbol']}",
                         f"No fill inside ₹{doc['entry_min']}–{doc['entry_max']} within the validity window. Status: MISSED ENTRY.",
                         doc["id"])
    else:
        if sig_status == "ACTIVE":
            if ltp <= doc["stop_loss"]:
                updates["status"] = "STOP_LOSS"
                updates["result"] = "LOSS"
                updates["exit_price"] = ltp
                updates["exit_time"] = now
                updates["pnl_points"] = round(ltp - doc["entry_price"], 2)
                add_event("STOP_LOSS", f"Stop-loss hit at ₹{ltp:.2f}.")
                await notify("STOP_LOSS", f"🛑 STOP LOSS — {doc['option_symbol']}",
                             f"Exit ₹{ltp:.2f}, P&L {updates['pnl_points']:+.2f} pts.", doc["id"])
            elif ltp >= doc["target1"]:
                updates["status"] = "TARGET1_HIT"
                add_event("TARGET1_HIT", f"Target 1 hit at ₹{ltp:.2f} — trailing to Target 2 / SL.")
                await notify("TARGET1", f"🎯 TARGET 1 HIT — {doc['option_symbol']}",
                             f"₹{ltp:.2f} (T1 ₹{doc['target1']}). Monitoring for Target 2; stop-loss trails at ₹{doc['stop_loss']}.", doc["id"])
        elif sig_status == "TARGET1_HIT":
            if ltp >= doc["target2"]:
                updates["status"] = "TARGET2_HIT"
                updates["result"] = "WIN"
                updates["exit_price"] = ltp
                updates["exit_time"] = now
                updates["pnl_points"] = round(ltp - doc["entry_price"], 2)
                add_event("TARGET2_HIT", f"Target 2 hit at ₹{ltp:.2f} — trade complete.")
                await notify("TARGET2", f"🏆 TARGET 2 HIT — {doc['option_symbol']}",
                             f"Exit ₹{ltp:.2f}, P&L {updates['pnl_points']:+.2f} pts.", doc["id"])
            elif ltp <= doc["stop_loss"]:
                updates["status"] = "STOP_LOSS"
                updates["result"] = "WIN" if ltp > doc["entry_price"] else "LOSS"
                updates["exit_price"] = ltp
                updates["exit_time"] = now
                updates["pnl_points"] = round(ltp - doc["entry_price"], 2)
                add_event("STOP_LOSS", f"Stop-loss hit after T1 at ₹{ltp:.2f}.")
                await notify("STOP_LOSS", f"🛑 EXIT AT SL — {doc['option_symbol']}",
                             f"Exited ₹{ltp:.2f} after Target 1, P&L {updates['pnl_points']:+.2f} pts.", doc["id"])
        # day-end square-off
        if updates.get("status") == sig_status and status.session_elapsed > SESSION_SECONDS - 10 * 60:
            updates["status"] = "EXPIRED"
            pnl = round(ltp - doc["entry_price"], 2)
            updates["result"] = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT")
            updates["exit_price"] = ltp
            updates["exit_time"] = now
            updates["pnl_points"] = pnl
            add_event("SQUARE_OFF", f"Session square-off at ₹{ltp:.2f}.")
            await notify("EXPIRED", f"⏱️ SESSION SQUARE-OFF — {doc['option_symbol']}",
                         f"Exited at ₹{ltp:.2f}, P&L {pnl:+.2f} pts.", doc["id"])
    if updates.get("status") and updates["status"] != sig_status:
        updates["updated_at"] = now
    await db.signals.update_one({"id": doc["id"]}, {"$set": updates})


# ---------------------------------------------------------------- paper trading

async def _paper_account_doc() -> dict:
    doc = await db.paper_account.find_one({"_id": "main"})
    if not doc:
        s = await get_settings()
        doc = {"_id": "main", "id": "main", "start_capital": s.paper.start_capital,
               "cash": s.paper.start_capital, "realized_pnl": 0.0, "peak_equity": s.paper.start_capital,
               "created_at": now_utc(), "updated_at": now_utc()}
        await db.paper_account.insert_one(doc)
    return doc


async def execute_paper(signal_id: str) -> tuple[bool, str, dict | None]:
    s = await get_settings()
    sig = await db.signals.find_one({"id": signal_id})
    if not sig:
        return False, "Signal not found.", None
    if sig["status"] not in ACTIVE_STATUSES:
        return False, f"Signal is {sig['status']} — only ACTIVE signals can be executed.", None
    if sig.get("paper_executed"):
        return False, "Signal already executed in the paper account.", None
    # duplicate active position guard
    if await db.paper_positions.find_one({"signal_id": signal_id, "status": "OPEN"}):
        return False, "An open paper position already exists for this signal.", None

    provider = get_provider()
    status = provider.get_status()
    anchor = await sim_anchor(sig["symbol"], provider._clock()[0])
    quote = provider.get_quote(sig["symbol"], anchor)
    chain = provider.build_chain(sig["symbol"], quote)
    row = next((r for r in chain.rows if r.expiry == sig["expiry"]
                and r.strike == sig["strike"] and r.option_type == sig["option_type"]), None)
    if not row:
        return False, "Option contract is no longer available from the provider.", None
    entry = min(max(row.ltp, sig["entry_min"]), sig["entry_max"])
    if row.ltp > sig["entry_max"] * 1.03:
        return False, (f"Executable price ₹{row.ltp:.2f} is above the entry tolerance "
                       f"₹{sig['entry_min']}–{sig['entry_max']} — entry missed (36.31)."), None

    lot = _lot_size(sig["symbol"])
    risk_per_lot = (entry - sig["stop_loss"]) * lot
    if risk_per_lot <= 0:
        return False, "Invalid risk per lot — cannot size the position.", None
    lots = int(s.risk.max_risk_per_trade // risk_per_lot)
    if lots <= 0:
        return False, (f"Maximum risk ₹{s.risk.max_risk_per_trade:.0f} is smaller than the risk of one lot "
                       f"(₹{risk_per_lot:,.0f}) — position size would be zero. Increase max risk per trade in Settings "
                       f"or pick a wider stop."), None
    qty = lots * lot
    acct = await _paper_account_doc()
    cost = entry * qty
    if acct["cash"] < cost:
        return False, (f"Insufficient virtual capital: needed ₹{cost:,.0f}, available ₹{acct['cash']:,.0f}."), None

    target = sig["target1"] if s.paper.exit_target == 1 else sig["target2"]
    slippage = s.paper.slippage_pct / 100
    entry_eff = round(entry * (1 + slippage), 2)
    pos = {
        "id": str(uuid.uuid4()), "signal_id": signal_id, "symbol": sig["symbol"],
        "option_symbol": sig["option_symbol"], "option_type": sig["option_type"],
        "strike": sig["strike"], "expiry": sig["expiry"], "side": "BUY",
        "qty": qty, "entry_price": entry_eff, "entry_time": now_utc(),
        "stop_loss": round(sig["stop_loss"] * (1 - slippage), 2),
        "target": round(target * (1 - slippage), 2), "exit_target": s.paper.exit_target,
        "status": "OPEN", "last_price": row.ltp, "close_reason": "",
    }
    await db.paper_positions.insert_one(pos)
    await db.paper_account.update_one(
        {"_id": "main"},
        {"$set": {"cash": acct["cash"] - cost, "updated_at": now_utc()}})
    await db.signals.update_one({"id": signal_id}, {"$set": {"paper_executed": True}})
    await notify("PAPER", f"📝 PAPER EXECUTED — {sig['option_symbol']}",
                 f"Virtual BUY {qty} @ ₹{entry_eff:.2f}, SL ₹{pos['stop_loss']}, target ₹{pos['target']} (T{s.paper.exit_target}). No real order placed.",
                 signal_id)
    return True, "Paper position opened.", pos


async def close_paper(position_id: str, reason: str = "MANUAL_EXIT") -> tuple[bool, str]:
    s = await get_settings()
    pos = await db.paper_positions.find_one({"id": position_id})
    if not pos or pos["status"] != "OPEN":
        return False, "Open paper position not found."
    provider = get_provider()
    anchor = await sim_anchor(pos["symbol"], provider._clock()[0])
    quote = provider.get_quote(pos["symbol"], anchor)
    chain = provider.build_chain(pos["symbol"], quote)
    row = next((r for r in chain.rows if r.expiry == pos["expiry"]
                and r.strike == pos["strike"] and r.option_type == pos["option_type"]), None)
    exit_px = row.ltp if row else pos["last_price"]
    return await _close_position(pos, exit_px * (1 - s.paper.slippage_pct / 100), reason)


async def _close_position(pos: dict, exit_price: float, reason: str) -> tuple[bool, str]:
    now = now_utc()
    pnl = round((exit_price - pos["entry_price"]) * pos["qty"], 2)
    await db.paper_positions.update_one(
        {"id": pos["id"]},
        {"$set": {"status": "CLOSED", "exit_price": round(exit_price, 2), "exit_time": now,
                  "realized_pnl": pnl, "close_reason": reason, "last_price": round(exit_price, 2)}})
    acct = await _paper_account_doc()
    await db.paper_account.update_one(
        {"_id": "main"},
        {"$set": {"cash": acct["cash"] + exit_price * pos["qty"],
                  "realized_pnl": acct["realized_pnl"] + pnl, "updated_at": now}})
    await notify("PAPER", f"📝 PAPER CLOSED — {pos['option_symbol']} ({reason})",
                 f"Exit ₹{exit_price:.2f}, P&L ₹{pnl:+,.0f} on {pos['qty']} qty.", pos.get("signal_id"))
    return True, f"Position closed ({reason}), P&L ₹{pnl:+,.0f}."


async def _monitor_paper(s: AppSettings, provider, status, now) -> None:
    open_pos = [p async for p in db.paper_positions.find({"status": "OPEN"})]
    if not open_pos:
        return
    chains: dict[str, ChainOut] = {}
    for pos in open_pos:
        if pos["symbol"] not in chains:
            anchor = await sim_anchor(pos["symbol"], provider._clock()[0])
            quote = provider.get_quote(pos["symbol"], anchor)
            raw = provider.build_chain(pos["symbol"], quote)
            chains[pos["symbol"]] = ChainOut(
                underlying=raw.underlying, spot=raw.spot, atm_strike=raw.atm_strike, ts=raw.ts,
                pcr=raw.pcr, max_pain=raw.max_pain, futures_price=raw.futures_price,
                basis=raw.basis, fut_oi_change=raw.fut_oi_change, regime=raw.regime,
                expiries=provider.next_expiries(pos["symbol"]),
                rows=[OptionRowOut(**r.__dict__) for r in raw.rows])
        chain = chains[pos["symbol"]]
        row = next((r for r in chain.rows if r.expiry == pos["expiry"]
                    and r.strike == pos["strike"] and r.option_type == pos["option_type"]), None)
        ltp = row.ltp if row else pos["last_price"]
        if ltp <= pos["stop_loss"]:
            await _close_position(pos, ltp, "STOP_LOSS")
        elif ltp >= pos["target"]:
            await _close_position(pos, ltp, f"TARGET{pos.get('exit_target', 1)}_HIT")
        elif status.status != "OPEN" or status.session_elapsed > SESSION_SECONDS - 10 * 60:
            await _close_position(pos, ltp, "SQUARE_OFF")
        else:
            await db.paper_positions.update_one(
                {"id": pos["id"]}, {"$set": {"last_price": ltp}})


async def paper_account_view() -> dict:
    s = await get_settings()
    acct = await _paper_account_doc()
    open_pos = [p async for p in db.paper_positions.find({"status": "OPEN"})]
    unreal = sum((p["last_price"] - p["entry_price"]) * p["qty"] for p in open_pos)
    equity = acct["cash"] + unreal
    peak = max(acct.get("peak_equity", equity), equity)
    dd = peak - equity
    since = ist_midnight_utc()
    closed_today = [p async for p in db.paper_positions.find(
        {"status": "CLOSED", "exit_time": {"$gte": since}})]
    daily_pnl = round(sum(p.get("realized_pnl") or 0 for p in closed_today) + unreal, 2)
    trades_today = len(closed_today) + len(open_pos)
    streak = 0
    for p in sorted(closed_today, key=lambda x: x.get("exit_time") or datetime.min.replace(tzinfo=UTC), reverse=True):
        if (p.get("realized_pnl") or 0) < 0:
            streak += 1
        else:
            break
    blocked = None
    if daily_pnl <= -abs(s.risk.daily_loss_limit):
        blocked = "🔴 DAILY LOSS LIMIT REACHED — paper trading paused for this session."
    elif streak >= s.risk.consecutive_loss_limit:
        blocked = "TRADING PAUSED — consecutive loss limit reached. Resets next session."
    await db.paper_account.update_one({"_id": "main"}, {"$set": {
        "peak_equity": peak, "updated_at": now_utc()}})
    return {
        "id": "main", "start_capital": acct["start_capital"], "cash": round(acct["cash"], 2),
        "equity": round(equity, 2), "realized_pnl": round(acct["realized_pnl"], 2),
        "unrealized_pnl": round(unreal, 2), "open_positions": len(open_pos),
        "peak_equity": round(peak, 2), "drawdown": round(dd, 2),
        "drawdown_pct": round(dd / peak * 100, 2) if peak else 0.0,
        "daily_pnl": daily_pnl, "trades_today": trades_today, "consecutive_losses": streak,
        "risk_blocked_reason": blocked,
        "created_at": acct.get("created_at", now_utc()), "updated_at": now_utc(),
    }
