"""Trading engines: Market Direction Engine, Option Selection Engine, Entry/SL/Target engine.

All three are pure functions over market data + an AppSettings object — no Mongo, no
HTTP — so the same code paths run live AND in the backtester (AC-23/55 reproducibility).
No single indicator decides anything; every factor contributes a configurable weight
(spec §5, §6) and every verdict carries its reasons (AC-09).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from lib.indicators import (
    atr,
    ema,
    macd,
    rel_volume,
    rolling_max,
    rolling_min,
    rsi,
    sma,
    swing_levels,
    vwap,
)
from models.trading import (
    AppSettings,
    ChainOut,
    FactorOut,
    OptionRowOut,
    StrategySettings,
)


# --------------------------------------------------------------------------- #
# Series container + indicator bundle
# --------------------------------------------------------------------------- #

@dataclass
class Series:
    ts: list                # UTC-aware datetimes, candle OPEN times
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    session_ids: list[str]  # per-candle session label (date or sim-day) for VWAP resets


@dataclass
class IndicatorBundle:
    ema_fast: np.ndarray
    ema_slow: np.ndarray
    ema_200: np.ndarray
    rsi_arr: np.ndarray
    macd_line: np.ndarray
    macd_sig: np.ndarray
    macd_hist: np.ndarray
    atr_arr: np.ndarray
    vwap_arr: np.ndarray
    rel_vol: np.ndarray
    prior_high: np.ndarray
    prior_low: np.ndarray
    supports: list[float]
    resistances: list[float]

    def summary(self, i: int) -> dict:
        def val(a: np.ndarray) -> float | None:
            v = a[i] if i < a.size else np.nan
            return None if np.isnan(v) else round(float(v), 2)

        return {
            "ema_fast": val(self.ema_fast),
            "ema_slow": val(self.ema_slow),
            "ema_200": val(self.ema_200),
            "rsi": None if np.isnan(self.rsi_arr[i]) else round(float(self.rsi_arr[i]), 1),
            "macd": val(self.macd_line),
            "macd_signal": val(self.macd_sig),
            "macd_hist": val(self.macd_hist),
            "atr": val(self.atr_arr),
            "vwap": val(self.vwap_arr),
            "rel_volume": None if np.isnan(self.rel_vol[i]) else round(float(self.rel_vol[i]), 2),
            "prior_high": val(self.prior_high),
            "prior_low": val(self.prior_low),
            "supports": [round(x, 2) for x in self.supports],
            "resistances": [round(x, 2) for x in self.resistances],
        }


def compute_indicators(series: Series, s: StrategySettings) -> IndicatorBundle:
    closes = series.c
    ema_f = ema(closes, s.ema_fast)
    ema_s = ema(closes, s.ema_slow)
    ema_200 = ema(closes, 200) if closes.size >= 200 else np.full(closes.shape, np.nan)
    rsi_arr = rsi(closes, s.rsi_period)
    macd_line, macd_sig, macd_hist = macd(closes)
    atr_arr = atr(series.h, series.l, closes, s.atr_period)
    vwap_arr = vwap(series.h, series.l, closes, series.v, series.session_ids)
    rel_vol = rel_volume(series.v, 20)
    prior_high = rolling_max(series.h, s.breakout_lookback)
    prior_low = rolling_min(series.l, s.breakout_lookback)
    supports, resistances = swing_levels(series.h, series.l)
    return IndicatorBundle(ema_f, ema_s, ema_200, rsi_arr, macd_line, macd_sig,
                           macd_hist, atr_arr, vwap_arr, rel_vol, prior_high,
                           prior_low, supports, resistances)


# --------------------------------------------------------------------------- #
# Market Direction Engine (§6)
# --------------------------------------------------------------------------- #

@dataclass
class DirectionResult:
    direction: str  # BULLISH | BEARISH | SIDEWAYS | NO_TRADE
    score: float    # signed, -100..100
    display_score: int
    factors: list[FactorOut] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    no_trade_reason: str | None = None
    conflict: bool = False


def evaluate_direction(series: Series, ind: IndicatorBundle, chain: ChainOut,
                       quote, s: StrategySettings, idx: int | None = None) -> DirectionResult:
    """Evaluate the direction at candle index `idx` (default: latest). For backtesting,
    pass a historical idx — all inputs are causal (indicator arrays use data ≤ i only)."""
    i = series.c.size - 1 if idx is None else idx
    close = float(series.c[i])
    w = s.weights
    total_w = w.trend + w.vwap + w.momentum + w.breakout + w.volume + w.fno
    factors: list[FactorOut] = []
    price = lambda x: f"₹{x:,.2f}"

    # ---- Trend (EMA structure) -------------------------------------------
    sub = 0.0
    notes = []
    ef, es, e2 = ind.ema_fast[i], ind.ema_slow[i], ind.ema_200[i]
    if not np.isnan(ef) and not np.isnan(es):
        sub += 0.6 if ef > es else -0.6
        notes.append(f"EMA{s.ema_fast} {'>' if ef > es else '<'} EMA{s.ema_slow}")
    if not np.isnan(ef):
        sub += 0.2 if close > ef else -0.2
        notes.append(f"price {'above' if close > ef else 'below'} EMA{s.ema_fast}")
    if not np.isnan(e2):
        sub += 0.2 if close > e2 else -0.2
        notes.append(f"price {'above' if close > e2 else 'below'} EMA200")
    factors.append(FactorOut(key="trend", label="Trend (EMA structure)",
                             state="bull" if sub > 0.1 else "bear" if sub < -0.1 else "neutral",
                             value=" | ".join(notes) or "insufficient data",
                             score=round(sub * w.trend, 1), reason="; ".join(notes)))

    # ---- VWAP --------------------------------------------------------------
    vw = ind.vwap_arr[i]
    f_vwap = 0.0
    if not np.isnan(vw):
        dev = (close - vw) / vw
        if abs(dev) <= 0.0005:
            f_vwap = 0.0
            v_txt = f"at VWAP (dev {dev * 100:.2f}%)"
        else:
            f_vwap = w.vwap * min(1.0, abs(dev) / 0.002) * (1 if dev > 0 else -1)
            v_txt = f"{'above' if dev > 0 else 'below'} VWAP by {dev * 100:.2f}%"
    else:
        v_txt = "VWAP unavailable"
    factors.append(FactorOut(key="vwap", label="VWAP position", value=v_txt,
                             state="bull" if f_vwap > 0.1 else "bear" if f_vwap < -0.1 else "neutral",
                             score=round(f_vwap, 1), reason=v_txt))

    # ---- Momentum (RSI + MACD) --------------------------------------------
    r = ind.rsi_arr[i]
    hist = ind.macd_hist[i]
    f_rsi = 0.0
    r_txt = "RSI unavailable"
    if not np.isnan(r):
        if r >= 55:
            f_rsi = w.momentum * 0.5 * min(1.0, (r - 50) / 20)
        elif r <= 45:
            f_rsi = w.momentum * 0.5 * min(1.0, (50 - r) / 20) * -1
        r_txt = f"RSI {r:.1f}" + (" (near overbought — capped)" if r > s.rsi_upper else " (near oversold — capped)" if r < s.rsi_lower else "")
        if r > s.rsi_upper:
            f_rsi *= 0.6
        if r < s.rsi_lower:
            f_rsi *= 0.6
    f_macd = 0.0
    m_txt = "MACD unavailable"
    if not np.isnan(hist):
        rising = i > 0 and not np.isnan(ind.macd_hist[i - 1]) and hist >= ind.macd_hist[i - 1]
        f_macd = w.momentum * 0.5 * (1.0 if hist > 0 and rising else 0.5 if hist > 0 else -1.0 if hist < 0 and not rising else -0.5)
        m_txt = f"MACD hist {hist:+.2f} ({'rising' if rising else 'falling'})"
    mom_score = f_rsi + f_macd
    factors.append(FactorOut(key="momentum", label="Momentum (RSI + MACD)",
                             value=f"{r_txt}; {m_txt}",
                             state="bull" if mom_score > 0.1 else "bear" if mom_score < -0.1 else "neutral",
                             score=round(mom_score, 1),
                             reason=f"{r_txt}; {m_txt}; RSI {'above' if not np.isnan(r) and r > 55 else 'below' if not np.isnan(r) and r < 45 else 'near'} 50"))

    # ---- Breakout / Breakdown ---------------------------------------------
    f_brk = 0.0
    brk_txt = f"inside {s.breakout_lookback}-bar range"
    ph, pl = ind.prior_high[i], ind.prior_low[i]
    if not np.isnan(ph) and close > ph * 1.0003:
        confirmed = not np.isnan(ind.rel_vol[i]) and ind.rel_vol[i] >= s.volume_multiplier
        f_brk = w.breakout * (1.0 if confirmed else 0.5)
        brk_txt = f"breakout above {ph:,.1f}" + (" with volume confirmation" if confirmed else " (volume below threshold — half weight)")
    elif not np.isnan(pl) and close < pl * 0.9997:
        confirmed = not np.isnan(ind.rel_vol[i]) and ind.rel_vol[i] >= s.volume_multiplier
        f_brk = -w.breakout * (1.0 if confirmed else 0.5)
        brk_txt = f"breakdown below {pl:,.1f}" + (" with volume confirmation" if confirmed else " (volume below threshold — half weight)")
    factors.append(FactorOut(key="breakout", label="Breakout / Breakdown", value=brk_txt,
                             state="bull" if f_brk > 0.1 else "bear" if f_brk < -0.1 else "neutral",
                             score=round(f_brk, 1), reason=brk_txt))

    # ---- Volume -------------------------------------------------------------
    rv = ind.rel_vol[i]
    f_vol = 0.0
    v_vol = "relative volume unavailable"
    if not np.isnan(rv):
        if rv >= s.volume_multiplier:
            up_candle = close >= float(series.o[i])
            f_vol = w.volume * (1 if up_candle else -1)
            v_vol = f"volume {rv:.2f}x average on {'up' if up_candle else 'down'} candle"
        elif rv >= 0.8:
            v_vol = f"volume {rv:.2f}x — neutral participation"
        else:
            v_vol = f"volume {rv:.2f}x — low participation"
    factors.append(FactorOut(key="volume", label="Volume confirmation", value=v_vol,
                             state="bull" if f_vol > 0.1 else "bear" if f_vol < -0.1 else "neutral",
                             score=round(f_vol, 1), reason=v_vol))

    # ---- F&O positioning ------------------------------------------------------
    f_fno = 0.0
    fno_txt = []
    if chain.pcr >= 1.1:
        f_fno += w.fno * 0.4 * min(1.0, (chain.pcr - 1.0) / 0.5)
        fno_txt.append(f"PCR {chain.pcr:.2f} — put-heavy (supportive)")
    elif chain.pcr <= 0.9:
        f_fno -= w.fno * 0.4 * min(1.0, (1.0 - chain.pcr) / 0.5)
        fno_txt.append(f"PCR {chain.pcr:.2f} — call-heavy (bearish lean)")
    else:
        fno_txt.append(f"PCR {chain.pcr:.2f} — balanced")
    price_up = not np.isnan(series.o[i]) and close > float(series.o[i])
    oi_chg = chain.fut_oi_change
    if price_up and oi_chg > 0:
        f_fno += w.fno * 0.3
        fno_txt.append("long build-up in futures (price up, OI up)")
    elif price_up and oi_chg <= 0:
        f_fno += w.fno * 0.15
        fno_txt.append("short covering in futures (price up, OI down)")
    elif not price_up and oi_chg > 0:
        f_fno -= w.fno * 0.3
        fno_txt.append("short build-up in futures (price down, OI up)")
    else:
        f_fno -= w.fno * 0.15
        fno_txt.append("long unwinding in futures (price down, OI down)")
    if chain.basis > 0:
        f_fno += w.fno * 0.15
        fno_txt.append(f"positive basis ₹{chain.basis:,.1f}")
    else:
        f_fno -= w.fno * 0.15
        fno_txt.append(f"negative basis ₹{chain.basis:,.1f}")
    factors.append(FactorOut(key="fno", label="F&O positioning", value="; ".join(fno_txt),
                             state="bull" if f_fno > 0.1 else "bear" if f_fno < -0.1 else "neutral",
                             score=round(f_fno, 1), reason="; ".join(fno_txt)))

    score = round(sum(f.score for f in factors), 1)
    tech = sum(f.score for f in factors if f.key != "fno")
    fno_score = next(f.score for f in factors if f.key == "fno")
    tol = s.conflict_tolerance
    conflict = (tech > tol and fno_score < -tol * 0.5) or (tech < -tol and fno_score > tol * 0.5)

    if conflict:
        return DirectionResult("NO_TRADE", score, int(abs(score)), factors,
                               no_trade_reason=f"Technical score ({tech:+.1f}) and F&O score ({fno_score:+.1f}) conflict beyond tolerance (±{tol:.0f}).",
                               conflict=True)
    if score >= s.min_signal_score:
        direction = "BULLISH"
    elif score <= -s.min_signal_score:
        direction = "BEARISH"
    else:
        return DirectionResult(
            "SIDEWAYS", score, int(abs(score)), factors,
            no_trade_reason=f"Directional conviction {abs(score):.0f}/100 is below the minimum score threshold ({s.min_signal_score:.0f}).",
        )
    reasons = [f"{'✓' if f.score > 0 else '✗'} {f.label}: {f.value}" for f in factors]
    return DirectionResult(direction, score, int(abs(score)), factors, reasons=reasons)


# --------------------------------------------------------------------------- #
# Option Selection Engine (§8)
# --------------------------------------------------------------------------- #

@dataclass
class OptionPick:
    row: OptionRowOut
    score: float
    score_breakdown: dict[str, float]
    t_years: float
    rejected: list[dict] = field(default_factory=list)


def _spread_pct(row: OptionRowOut) -> float:
    mid = (row.bid + row.ask) / 2
    if mid <= 0:
        return 999.0
    return (row.ask - row.bid) / mid * 100


def select_option(chain: ChainOut, direction: str, os_settings, s: StrategySettings,
                  ist_now=None) -> OptionPick | None:
    """Rank the eligible side (CE on BULLISH, PE on BEARISH); None ⇒ NO TRADE (AC-18)."""
    from datetime import datetime as _dt

    from lib.dates import IST

    now = ist_now or _dt.now(IST)
    want_type = "CE" if direction == "BULLISH" else "PE"
    side_rows = [r for r in chain.rows if r.option_type == want_type]
    expiries = sorted({r.expiry for r in side_rows})
    if not expiries:
        return None
    all_strikes = sorted({r.strike for r in chain.rows})
    step = int(min((b - a for a, b in zip(all_strikes, all_strikes[1:]) if b > a), default=50)) or 50
    w = os_settings.weights
    rejected: list[dict] = []
    best: OptionPick | None = None

    for expiry in expiries:
        exp_dt = _dt.fromisoformat(expiry).replace(hour=15, minute=30, tzinfo=IST)
        t_years = (exp_dt - now).total_seconds() / (365 * 24 * 3600)
        if t_years <= 0:
            continue
        rows = [r for r in side_rows if r.expiry == expiry and abs(r.strike - chain.atm_strike) <= os_settings.atm_range * step]
        for row in rows:
            hard_rejects = []
            sp = _spread_pct(row)
            if row.open_interest < os_settings.min_oi:
                hard_rejects.append(f"OI {row.open_interest:,} < minimum {os_settings.min_oi:,}")
            if row.volume < os_settings.min_volume:
                hard_rejects.append(f"volume {row.volume:,} < minimum {os_settings.min_volume:,}")
            if sp > os_settings.max_spread_pct:
                hard_rejects.append(f"spread {sp:.2f}% > maximum {os_settings.max_spread_pct}%")
            if row.ltp < os_settings.min_premium:
                hard_rejects.append(f"premium ₹{row.ltp:.2f} < minimum ₹{os_settings.min_premium:.0f}")
            if hard_rejects:
                rejected.append({"strike": row.strike, "expiry": expiry, "reasons": hard_rejects,
                                 "score": 0.0, "spread_pct": round(sp, 2)})
                continue
            # distance is in rupees; normalise by (strike count × step) so it is unit-correct
            near = 1.0 - min(1.0, abs(row.strike - chain.atm_strike) / (os_settings.atm_range * 0.75 * step + 1e-9))
            s_liq = w.liquidity * (0.6 * min(1.0, row.volume / max(os_settings.min_volume, 1)) + 0.4 * min(1.0, row.open_interest / max(os_settings.min_oi, 1)))
            s_money = w.moneyness * near
            s_oi = w.oi_alignment * (1.0 if row.change_in_oi > 0 else 0.3)
            s_iv = w.iv * (1.0 if 0.09 <= row.iv <= 0.22 else 0.4 if row.iv < 0.09 else 0.2)
            s_spread = w.spread * max(0.0, 1.0 - sp / max(os_settings.max_spread_pct, 0.1))
            score = round(s_liq + s_money + s_oi + s_iv + s_spread, 1)
            if best is None or score > best.score:
                best = OptionPick(row=row, score=score, t_years=t_years,
                                  score_breakdown={"liquidity": round(s_liq, 1), "moneyness": round(s_money, 1),
                                                   "oi_alignment": round(s_oi, 1), "iv": round(s_iv, 1),
                                                   "spread": round(s_spread, 1)},
                                  rejected=rejected)
    if best is None or best.score < os_settings.min_option_score:
        return None
    return best


# --------------------------------------------------------------------------- #
# Entry / Stop Loss / Target engine (§9)
# --------------------------------------------------------------------------- #

@dataclass
class Levels:
    entry_min: float
    entry_max: float
    stop_loss: float
    target1: float
    target2: float
    risk_points: float
    risk_reward: float


def calc_levels(pick: OptionPick, atr_val: float | None, s: StrategySettings) -> Levels | None:
    """ATR/premium-aware levels. Returns None when a valid SL cannot be computed (AC-20)."""
    mid = (pick.row.bid + pick.row.ask) / 2
    if mid <= 0:
        return None
    entry_min = round(mid * (1 - s.entry_range_pct / 100), 2)
    entry_max = round(mid * (1 + s.entry_range_pct / 100), 2)
    risk = mid * s.sl_pct_of_premium / 100
    spread = pick.row.ask - pick.row.bid
    risk = max(risk, spread, 1.0)
    sl = round(mid - risk, 2)
    if sl <= 0 or risk <= 0:
        return None
    expected_move = (abs(pick.row.delta) * (atr_val or 0.0) * 6.0) if atr_val else 0.0
    t1_dist = max(risk * s.t1_rr, min(expected_move, risk * (s.t2_rr - 0.2)))
    t1 = round(mid + t1_dist, 2)
    t2 = round(mid + risk * s.t2_rr, 2)
    rr = round((t1 - mid) / (mid - sl), 2)
    return Levels(entry_min, entry_max, sl, t1, t2, round(mid - sl, 2), rr)


def strength_label(score: float, min_score: float = 50) -> str:
    """Strength bands are relative to the configured minimum score, because the minimum is
    itself configurable and was calibrated on historical score distribution (spec §10/36.40):
    on 6 months of NIFTY 5m data the |score| distribution runs p50≈26, p90≈45, p95≈50, max≈74,
    so fixed 70/80/90 bands would never be reached."""
    if score >= min_score + 25:
        return "Very Strong"
    if score >= min_score + 12:
        return "Strong"
    if score >= min_score:
        return "Moderate"
    return "Weak"


def option_symbol(symbol: str, strike: float, option_type: str) -> str:
    strike_txt = str(int(strike)) if float(strike).is_integer() else f"{strike:.2f}"
    return f"{symbol}{strike_txt}{option_type}"
