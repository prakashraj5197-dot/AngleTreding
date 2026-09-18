"""Market data routes: status, quotes, candles, option chain, freshness, health."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from lib.db import db
from lib.dates import UTC, now_utc
from lib.engine import compute_indicators
from lib.signal_engine import (
    get_provider,
    get_settings,
    load_series,
    sim_anchor,
)
from lib.sim_provider import INSTRUMENTS
from models.trading import (
    Candle,
    ChainOut,
    FreshnessOut,
    HealthOut,
    MarketStatusOut,
    OptionRowOut,
    QuoteOut,
)

router = APIRouter(tags=["market"])


@router.get("/market/status", response_model=MarketStatusOut)
async def market_status():
    await get_settings()
    st = get_provider().get_status()
    return MarketStatusOut(**st.__dict__)


@router.get("/market/instruments")
async def instruments():
    return [{"symbol": i.symbol, "name": i.name, "kind": i.kind,
             "lot_size": i.lot_size, "strike_step": i.strike_step}
            for i in INSTRUMENTS.values()]


async def _quote_out(symbol: str) -> QuoteOut:
    provider = get_provider()
    anchor = await sim_anchor(symbol, provider._clock()[0])
    q = provider.get_quote(symbol, anchor)
    return QuoteOut(
        symbol=q.symbol, name=INSTRUMENTS[symbol].name, ltp=q.ltp, open=q.open,
        high=q.high, low=q.low, prev_close=q.prev_close, change=q.change,
        change_pct=q.change_pct, volume=q.volume, vwap=q.vwap, ts=q.ts,
        market_status=q.market_status, session_elapsed=q.session_elapsed,
        session_mode=q.session_mode, simulated=True, regime=q.regime,
    )


@router.get("/market/quotes", response_model=list[QuoteOut])
async def quotes(symbols: str = Query("NIFTY,BANKNIFTY")):
    await get_settings()
    out = []
    for sym in [s.strip().upper() for s in symbols.split(",") if s.strip()]:
        if sym not in INSTRUMENTS:
            raise HTTPException(status_code=404, detail=f"Unknown symbol '{sym}'.")
        out.append(await _quote_out(sym))
    return out


@router.get("/market/quote/{symbol}", response_model=QuoteOut)
async def quote(symbol: str):
    symbol = symbol.upper()
    if symbol not in INSTRUMENTS:
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{symbol}'.")
    await get_settings()
    return await _quote_out(symbol)


@router.get("/market/candles/{symbol}", response_model=list[Candle])
async def candles(symbol: str, timeframe: str = "5m", limit: int = 180):
    symbol = symbol.upper()
    if symbol not in INSTRUMENTS:
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{symbol}'.")
    if timeframe not in ("1m", "5m", "15m"):
        raise HTTPException(status_code=422, detail="timeframe must be one of 1m, 5m, 15m.")
    await get_settings()
    series = await load_series(symbol, timeframe, min(max(limit, 10), 800))
    return [Candle(symbol=symbol, timeframe=timeframe, ts=series.ts[i],
                   o=float(series.o[i]), h=float(series.h[i]), l=float(series.l[i]),
                   c=float(series.c[i]), v=float(series.v[i]))
            for i in range(series.c.size)]


@router.get("/market/chain/{symbol}", response_model=ChainOut)
async def option_chain(symbol: str, expiry: str | None = None, strikes: int = 10):
    symbol = symbol.upper()
    if symbol not in INSTRUMENTS:
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{symbol}'.")
    await get_settings()
    provider = get_provider()
    anchor = await sim_anchor(symbol, provider._clock()[0])
    q = provider.get_quote(symbol, anchor)
    raw = provider.build_chain(symbol, q)
    expiries = provider.next_expiries(symbol)
    step = INSTRUMENTS[symbol].strike_step
    rows = [r for r in raw.rows
            if (expiry is None or r.expiry == expiry)
            and abs(r.strike - raw.atm_strike) <= max(1, min(strikes, 20)) * step]
    return ChainOut(
        underlying=raw.underlying, spot=raw.spot, atm_strike=raw.atm_strike, ts=raw.ts,
        pcr=raw.pcr, max_pain=raw.max_pain, futures_price=raw.futures_price,
        basis=raw.basis, fut_oi_change=raw.fut_oi_change, regime=raw.regime,
        expiries=expiries, rows=[OptionRowOut(**r.__dict__) for r in rows],
    )


@router.get("/market/freshness", response_model=FreshnessOut)
async def freshness():
    s = await get_settings()
    provider = get_provider()
    anchor = await sim_anchor("NIFTY", provider._clock()[0])
    q = provider.get_quote("NIFTY", anchor)
    age = (now_utc() - q.ts).total_seconds()
    out = FreshnessOut(
        price_age_s=round(age, 2), option_age_s=round(age, 2), chain_age_s=round(age, 2),
        price_ok=age <= s.data.price_fresh_s, option_ok=age <= s.data.option_fresh_s,
        chain_ok=age <= s.data.chain_fresh_s, forced_stale=provider.force_stale,
    )
    out.stale = not (out.price_ok and out.option_ok and out.chain_ok)
    return out


@router.get("/health", response_model=HealthOut)
async def health():
    s = await get_settings()
    database = "ok"
    try:
        await db.command("ping")
    except Exception:
        database = "down"
    fresh = await freshness()
    last = await db.signals.find_one({}, sort=[("created_at", -1)])
    active = await db.signals.count_documents({"status": {"$in": ["ACTIVE", "TARGET1_HIT"]}})
    provider = get_provider()
    st = provider.get_status()
    return HealthOut(
        app="ok" if database == "ok" and not fresh.stale else "degraded",
        database=database,
        provider="connected" if not provider.force_stale else "disconnected",
        provider_mode=f"simulated/{st.session_mode}",
        data_freshness=fresh,
        last_signal_at=last.get("created_at") if last else None,
        active_signals=active,
        server_time_utc=now_utc(),
    )
