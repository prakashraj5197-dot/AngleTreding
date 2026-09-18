"""Option scanner routes — ranked contracts with rejection reasons (AC-16/17/18/47)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from lib.dates import IST, now_ist
from lib.engine import _spread_pct
from lib.signal_engine import get_provider, get_settings, sim_anchor
from lib.sim_provider import INSTRUMENTS
from models.trading import OptionRowOut

router = APIRouter(tags=["scanner"])


@router.get("/scanner/{symbol}")
async def scan(symbol: str, expiry: str | None = None, strikes: int = 10,
               side: str | None = None):
    """Rank every contract in the ATM±N window, with per-contract score + rejections."""
    symbol = symbol.upper()
    if symbol not in INSTRUMENTS:
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{symbol}'.")
    s = await get_settings()
    cfg = s.option_selection
    provider = get_provider()
    anchor = await sim_anchor(symbol, provider._clock()[0])
    quote = provider.get_quote(symbol, anchor)
    raw = provider.build_chain(symbol, quote)
    expiries = provider.next_expiries(symbol)
    chosen = expiry or (expiries[0] if expiries else None)
    if chosen and chosen not in expiries:
        raise HTTPException(status_code=422, detail=f"Expiry '{chosen}' is not a listed contract expiry.")
    step = INSTRUMENTS[symbol].strike_step
    window = max(1, min(strikes, 20)) * step
    w = cfg.weights
    now = now_ist()
    rows: list[dict] = []
    from datetime import datetime as _dt

    for r in raw.rows:
        if r.expiry != chosen or abs(r.strike - raw.atm_strike) > window:
            continue
        if side and r.option_type != side.upper():
            continue
        exp_dt = _dt.fromisoformat(r.expiry).replace(hour=15, minute=30, tzinfo=IST)
        t_years = max((exp_dt - now).total_seconds(), 3600) / (365 * 24 * 3600)
        sp = _spread_pct(OptionRowOut(**r.__dict__))
        rejects: list[str] = []
        if r.open_interest < cfg.min_oi:
            rejects.append(f"OI {r.open_interest:,} < {cfg.min_oi:,}")
        if r.volume < cfg.min_volume:
            rejects.append(f"Volume {r.volume:,} < {cfg.min_volume:,}")
        if sp > cfg.max_spread_pct:
            rejects.append(f"Spread {sp:.2f}% > {cfg.max_spread_pct}%")
        if r.ltp < cfg.min_premium:
            rejects.append(f"Premium ₹{r.ltp:.2f} < ₹{cfg.min_premium:.0f}")
        near = 1.0 - min(1.0, abs(r.strike - raw.atm_strike) / (cfg.atm_range * step * 0.75 + 1e-9))
        s_liq = w.liquidity * (0.6 * min(1.0, r.volume / max(cfg.min_volume, 1)) + 0.4 * min(1.0, r.open_interest / max(cfg.min_oi, 1)))
        s_money = w.moneyness * near
        s_oi = w.oi_alignment * (1.0 if r.change_in_oi > 0 else 0.3)
        s_iv = w.iv * (1.0 if 0.09 <= r.iv <= 0.22 else 0.4 if r.iv < 0.09 else 0.2)
        s_spread = w.spread * max(0.0, 1.0 - sp / max(cfg.max_spread_pct, 0.1))
        score = 0.0 if rejects else round(s_liq + s_money + s_oi + s_iv + s_spread, 1)
        rows.append({
            **r.__dict__,
            "spread_pct": round(sp, 3),
            "score": score,
            "score_breakdown": {"liquidity": round(s_liq, 1), "moneyness": round(s_money, 1),
                                "oi_alignment": round(s_oi, 1), "iv": round(s_iv, 1),
                                "spread": round(s_spread, 1)},
            "eligible": not rejects and score >= cfg.min_option_score,
            "rejected": bool(rejects),
            "reject_reasons": rejects,
            "below_min_score": not rejects and score < cfg.min_option_score,
            "t_days": round(t_years * 365, 2),
        })
    ranked = sorted([r for r in rows if r["eligible"]], key=lambda r: r["score"], reverse=True)
    top_ce = next((r for r in ranked if r["option_type"] == "CE"), None)
    top_pe = next((r for r in ranked if r["option_type"] == "PE"), None)
    return {
        "underlying": symbol,
        "spot": raw.spot,
        "atm_strike": raw.atm_strike,
        "strike_step": step,
        "expiry": chosen,
        "expiries": expiries,
        "ts": raw.ts,
        "pcr": raw.pcr,
        "max_pain": raw.max_pain,
        "futures_price": raw.futures_price,
        "basis": raw.basis,
        "regime": raw.regime,
        "market_status": quote.market_status,
        "thresholds": {"min_oi": cfg.min_oi, "min_volume": cfg.min_volume,
                       "max_spread_pct": cfg.max_spread_pct, "min_premium": cfg.min_premium,
                       "min_option_score": cfg.min_option_score, "atm_range": cfg.atm_range},
        "rows": sorted(rows, key=lambda r: (r["strike"], r["option_type"])),
        "top_ranked": ranked[:8],
        "recommended_ce": top_ce,
        "recommended_pe": top_pe,
        "eligible_count": len(ranked),
        "rejected_count": sum(1 for r in rows if r["rejected"]),
    }
