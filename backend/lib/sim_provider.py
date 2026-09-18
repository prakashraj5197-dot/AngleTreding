"""Market-data provider layer.

`MarketDataProvider` is the ONLY surface the engines see (spec §2: provider integration
must stay isolated behind an interface so the provider can be swapped later — a real
broker feed like Angel One/Kite implements the same ABC).

`SimulatedProvider` is the built-in v1 provider: a deterministic, seeded NSE-style
synthetic feed covering NIFTY / BANKNIFTY / F&O stocks with
  • 1-minute OHLCV(+OI) candle generation, aggregated to 5m/15m
  • a simulated session clock (09:15–15:30 IST) in two modes:
      - "always_on": the demo session loops continuously (clearly badged SIMULATED)
      - "market_hours": honours the real NSE clock incl. weekends (demo of MARKET CLOSED)
  • live quotes with per-second intra-minute interpolation
  • full option chains (ATM±10 strikes, weekly/monthly expiries) with IV smile,
    Black-Scholes greeks, volume/OI/change-in-OI, bid/ask spreads, PCR and max pain.

Everything is deterministic: same (symbol, day-key, anchor) ⇒ same data, which makes
backtests reproducible (AC-55).
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np

from lib import option_math
from lib.dates import (
    IST,
    MARKET_CLOSE,
    MARKET_OPEN,
    SESSION_SECONDS,
    session_elapsed_seconds,
)

# --------------------------------------------------------------------------- #
# Instrument registry
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    kind: str          # INDEX | STOCK
    base_price: float
    strike_step: int
    lot_size: int
    base_volume: float
    vol_scale: float   # daily vol multiplier vs NIFTY
    weekly_expiries: bool


INSTRUMENTS: dict[str, Instrument] = {
    i.symbol: i
    for i in [
        Instrument("NIFTY", "NIFTY 50", "INDEX", 24850.0, 50, 75, 220_000, 1.00, True),
        Instrument("BANKNIFTY", "BANK NIFTY", "INDEX", 53200.0, 100, 35, 95_000, 1.25, False),
        Instrument("RELIANCE", "Reliance Industries", "STOCK", 2955.0, 20, 500, 42_000, 1.05, False),
        Instrument("HDFCBANK", "HDFC Bank", "STOCK", 1712.0, 20, 550, 38_000, 0.95, False),
        Instrument("INFY", "Infosys", "STOCK", 1875.0, 20, 400, 30_000, 1.10, False),
        Instrument("TCS", "Tata Consultancy Services", "STOCK", 4120.0, 20, 175, 18_000, 0.90, False),
    ]
}

REGIMES = ("trend_up", "trend_down", "range", "high_vol", "low_vol")
# per-regime day parameters: (drift_lo, drift_hi, vol_mult, volume_mult)
REGIME_PARAMS = {
    "trend_up": (0.0025, 0.0075, 0.9, 1.15),
    "trend_down": (-0.0075, -0.0025, 1.0, 1.20),
    "range": (-0.0020, 0.0020, 0.75, 0.85),
    "high_vol": (-0.0040, 0.0040, 1.9, 1.60),
    "low_vol": (-0.0012, 0.0012, 0.55, 0.65),
}


def _stable_hash(*parts) -> int:
    digest = hashlib.md5("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _seed_rng(*parts) -> np.random.Generator:
    return np.random.default_rng(_stable_hash(*parts))


# --------------------------------------------------------------------------- #
# Provider interface + simulated implementation
# --------------------------------------------------------------------------- #

@dataclass
class Quote:
    symbol: str
    ltp: float
    open: float
    high: float
    low: float
    prev_close: float
    volume: float
    vwap: float
    change: float          # absolute vs prev close
    change_pct: float
    ts: datetime           # UTC-aware data timestamp (freshness anchor)
    market_status: str     # OPEN | CLOSED
    session_elapsed: int   # seconds since 09:15 IST of the simulated session
    session_mode: str
    simulated: bool = True
    regime: str = "range"


@dataclass
class OptionRow:
    underlying: str
    expiry: str            # YYYY-MM-DD
    strike: float
    option_type: str       # CE | PE
    ltp: float
    bid: float
    ask: float
    volume: int
    open_interest: int
    change_in_oi: int
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float
    moneyness: str = ""    # ITM | ATM | OTM (filled by builder)
    ts: datetime | None = None


@dataclass
class ChainSnapshot:
    underlying: str
    spot: float
    atm_strike: float
    ts: datetime
    rows: list[OptionRow] = field(default_factory=list)
    pcr: float = 0.0
    max_pain: float = 0.0
    futures_price: float = 0.0
    basis: float = 0.0
    fut_oi_change: int = 0
    regime: str = "range"


@dataclass
class MarketStatusInfo:
    status: str            # OPEN | CLOSED
    ist_time: str
    ist_date: str
    session_elapsed: int
    session_mode: str
    simulated: bool
    note: str = ""


class MarketDataProvider(ABC):
    """Swap-in interface for any market-data vendor."""

    @abstractmethod
    def get_status(self) -> MarketStatusInfo: ...

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    def get_option_chain(self, symbol: str) -> ChainSnapshot: ...

    @abstractmethod
    def price_option(self, spot: float, strike: float, t_years: float, iv: float,
                     call: bool) -> float:
        """Model price for historical/backtest repricing (no live feed needed)."""


class SimulatedProvider(MarketDataProvider):
    """Deterministic synthetic NSE-style feed (v1 default)."""

    SESSION_MODE_DEFAULT = "always_on"
    # anchor so the always-on session clock is stable across restarts
    _EPOCH = datetime(2024, 1, 1, 9, 15, tzinfo=IST)

    def __init__(self) -> None:
        self.session_mode = self.SESSION_MODE_DEFAULT
        self.force_stale = False
        self.frozen_at: datetime | None = None
        # per-symbol live day cache: {symbol: (day_key, anchor_close, closes array, opens, vwap)}
        self._day_cache: dict[str, tuple] = {}
        # last chain snapshot per symbol, for change-in-OI deltas
        self._last_oi: dict[str, dict[tuple, int]] = {}

    def freeze_feed(self) -> None:
        """Fault injection: freeze the data timestamp — every quote goes stale (AC-02/74)."""
        if self.frozen_at is None:
            self.frozen_at = datetime.now(UTC_naive_guard())

    def unfreeze_feed(self) -> None:
        self.frozen_at = None

    # ---------------- session clock ----------------

    def set_session_mode(self, mode: str) -> None:
        if mode in ("always_on", "market_hours"):
            self.session_mode = mode

    def _clock(self) -> tuple[str, int, str]:
        """Returns (day_key, elapsed_seconds, status)."""
        now = datetime.now(IST)
        if self.session_mode == "market_hours":
            open_now = now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE
            if open_now:
                return now.strftime("%Y-%m-%d"), session_elapsed_seconds(now), "OPEN"
            # Market is closed: anchor to the most recent COMPLETED session. After the close
            # on a weekday that is today; before the open (or at a weekend) walk back to the
            # previous weekday.
            d = now
            if now.time() < MARKET_OPEN:
                d -= timedelta(days=1)
            while d.weekday() >= 5:
                d -= timedelta(days=1)
            return d.strftime("%Y-%m-%d"), SESSION_SECONDS, "CLOSED"
        # always_on: continuous simulated session, 1:1 wall-clock speed
        total = (now - self._EPOCH).total_seconds()
        day_number = int(total // SESSION_SECONDS)
        elapsed = int(total % SESSION_SECONDS)
        return f"sim-{day_number}", elapsed, "OPEN"

    def get_status(self) -> MarketStatusInfo:
        day_key, elapsed, status = self._clock()
        note = ""
        if self.session_mode == "always_on":
            note = "Simulated continuous session (always-on demo mode)"
        elif status == "CLOSED":
            note = "NSE session closed (09:15–15:30 IST, Mon–Fri)"
        return MarketStatusInfo(
            status=status,
            ist_time=datetime.now(IST).strftime("%H:%M:%S"),
            ist_date=datetime.now(IST).strftime("%Y-%m-%d"),
            session_elapsed=elapsed,
            session_mode=self.session_mode,
            simulated=True,
            note=note,
        )

    # ---------------- synthetic candle engine ----------------

    def _regime_for(self, symbol: str, day_key: str) -> str:
        # month-level bias + day noise ⇒ multi-day trend runs (regime coverage, 36.34)
        month_key = day_key[:7]
        bias = _stable_hash("regime-month", symbol, month_key) % 100
        noise = _stable_hash("regime-day", symbol, day_key) % 100
        if bias < 30:      # bullish month
            return "trend_up" if noise < 62 else ("range" if noise < 85 else "high_vol")
        if bias < 55:      # bearish month
            return "trend_down" if noise < 62 else ("range" if noise < 85 else "high_vol")
        if bias < 80:      # range-bound month
            return "range" if noise < 70 else ("low_vol" if noise < 88 else "trend_up")
        return "high_vol" if noise < 25 else ("low_vol" if noise < 60 else "range")

    def _day_path(self, symbol: str, day_key: str, prev_close: float):
        """Deterministic 1-minute path for one session. Returns (opens, highs, lows, closes, volumes, ois)."""
        inst = INSTRUMENTS[symbol]
        regime = self._regime_for(symbol, day_key)
        drift_lo, drift_hi, vol_mult, vol_mult_v = REGIME_PARAMS[regime]
        rng = _seed_rng("day", symbol, day_key)

        n = 375
        annual_vol = 0.13 * inst.vol_scale * vol_mult
        minute_vol = annual_vol / math.sqrt(252 * 375)
        day_drift = rng.uniform(drift_lo, drift_hi)
        gap = rng.normal(0, annual_vol / math.sqrt(252) * 0.35)

        open_px = prev_close * (1 + gap)
        close_target = open_px * (1 + day_drift)

        # brownian bridge: noise that starts and ends at zero, plus drift to target
        noise = rng.normal(0, minute_vol, n)
        noise = np.concatenate(([0.0], np.cumsum(noise)))[:-1]
        # remove terminal drift of the random walk so the bridge lands on close_target
        noise -= np.linspace(0, noise[-1], n)
        t = np.linspace(0, 1, n)
        base = open_px + (close_target - open_px) * t + noise

        # 0-2 intraday impulses (breakouts / breakdowns)
        for _ in range(int(rng.integers(0, 3))):
            start = int(rng.integers(30, n - 60))
            length = int(rng.integers(15, 50))
            kick = rng.normal(0, 1) * annual_vol / math.sqrt(252) * 0.55
            base[start : start + length] += np.linspace(0, kick * open_px, length)

        closes = base
        opens = np.concatenate(([open_px], closes[:-1]))
        span = np.abs(np.diff(np.concatenate(([open_px], closes)))) * 0.5 + minute_vol * open_px * 0.8
        highs = np.maximum(opens, closes) + span * rng.uniform(0.3, 1.0, n)
        lows = np.minimum(opens, closes) - span * rng.uniform(0.3, 1.0, n)

        # U-shaped volume profile with trend-day ramp
        u = 0.55 + 0.9 * ((t - 0.5) ** 2) * 2.0
        ramp = 1.0 + (t if regime in ("trend_up", "trend_down") else 0) * 0.6
        vol_noise = rng.lognormal(0, 0.25, n)
        volumes = inst.base_volume * u * ramp * vol_mult_v * vol_noise / n * 375

        prev_oi = inst.base_volume * 8
        oi_flow = rng.normal(0, 0.004, n).cumsum()
        ois = np.maximum(prev_oi * (1 + oi_flow), prev_oi * 0.5)

        return opens, highs, lows, closes, volumes, ois, regime

    def _live_day(self, symbol: str, day_key: str, anchor_close: float):
        """Full-day close series for the live session, cached per (symbol, day_key, anchor)."""
        cached = self._day_cache.get(symbol)
        if cached and cached[0] == day_key and abs(cached[1] - anchor_close) < 1e-6:
            return cached[2:]
        opens, highs, lows, closes, vols, ois, regime = self._day_path(symbol, day_key, anchor_close)
        # session VWAP
        tp = (highs + lows + closes) / 3.0
        vwap_series = np.cumsum(tp * vols) / np.maximum(np.cumsum(vols), 1e-9)
        self._day_cache[symbol] = (day_key, anchor_close, opens, highs, lows, closes, vols, vwap_series, regime)
        return self._day_cache[symbol][2:]

    def live_anchor(self, symbol: str, last_stored_close: float | None) -> float:
        return float(last_stored_close) if last_stored_close else INSTRUMENTS[symbol].base_price

    # ---------------- quotes ----------------

    def get_quote(self, symbol: str, anchor_close: float | None = None) -> Quote:
        inst = INSTRUMENTS[symbol]
        day_key, elapsed, status = self._clock()
        anchor = anchor_close if anchor_close else inst.base_price
        opens, highs, lows, closes, vols, _ois, regime = self._live_day(symbol, day_key, anchor)
        m = min(int(elapsed // 60), 374)
        s_in_min = (elapsed % 60) / 60.0
        prev_c = closes[m - 1] if m > 0 else opens[0]
        ltp = prev_c + (closes[m] - prev_c) * s_in_min if status == "OPEN" else closes[-1]
        day_high = float(highs[: m + (1 if status == "OPEN" else 0)].max())
        day_low = float(lows[: m + (1 if status == "OPEN" else 0)].min())
        day_open = float(opens[0])
        vol_today = float(vols[: m + 1].sum())
        vwap_today = float(vols[: m + 1].sum() and (vols[: m + 1] * ((highs[: m + 1] + lows[: m + 1] + closes[: m + 1]) / 3)).sum() / max(vols[: m + 1].sum(), 1e-9))
        prev_close = anchor
        data_ts = self.frozen_at or datetime.now(UTC_naive_guard())
        return Quote(
            symbol=symbol,
            ltp=round(float(ltp), 2),
            open=round(day_open, 2),
            high=round(day_high, 2),
            low=round(day_low, 2),
            prev_close=round(prev_close, 2),
            volume=round(vol_today, 0),
            vwap=round(vwap_today, 2),
            change=round(float(ltp) - prev_close, 2),
            change_pct=round((float(ltp) / prev_close - 1) * 100, 2),
            ts=data_ts,
            market_status=status,
            session_elapsed=elapsed,
            session_mode=self.session_mode,
            regime=regime,
        )

    def today_candles(self, symbol: str, anchor_close: float | None = None,
                      timeframe: str = "1m") -> list[dict]:
        """Today's (sim session) 1m candles; aggregated up to 5m/15m. ts = candle OPEN, UTC."""
        day_key, elapsed, status = self._clock()
        anchor = anchor_close if anchor_close else INSTRUMENTS[symbol].base_price
        opens, highs, lows, closes, vols, _ois, regime = self._live_day(symbol, day_key, anchor)
        done = min(int(elapsed // 60), 375) if status == "OPEN" else 375
        if status != "OPEN":
            done = 375
        rows_1m = self._candle_dicts(symbol, "1m", opens, highs, lows, closes, vols, done, day_key)
        if timeframe == "1m":
            return rows_1m
        per = 5 if timeframe == "5m" else 15
        return self._aggregate(rows_1m, per)

    @staticmethod
    def _candle_dicts(symbol, tf, opens, highs, lows, closes, vols, count, day_key) -> list[dict]:
        out: list[dict] = []
        for i in range(count):
            out.append({
                "symbol": symbol,
                "timeframe": tf,
                "ts": session_minute_to_utc(day_key, i),
                "o": round(float(opens[i]), 2),
                "h": round(float(highs[i]), 2),
                "l": round(float(lows[i]), 2),
                "c": round(float(closes[i]), 2),
                "v": round(float(vols[i]), 0),
            })
        return out

    @staticmethod
    def _aggregate(rows_1m: list[dict], per: int) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(rows_1m), per):
            chunk = rows_1m[i : i + per]
            if not chunk:
                continue
            out.append({
                "symbol": chunk[0]["symbol"],
                "timeframe": f"{per}m" if per != 1 else "1m",
                "ts": chunk[0]["ts"],
                "o": chunk[0]["o"],
                "h": max(r["h"] for r in chunk),
                "l": min(r["l"] for r in chunk),
                "c": chunk[-1]["c"],
                "v": sum(r["v"] for r in chunk),
            })
        return out

    # ---------------- history generation (used by seed.py) ----------------

    def generate_history(self, symbol: str, day_keys: list[str], start_close: float):
        """Yield ('1m'|'5m'|'15m', [candle docs]) batches for consecutive trading days."""
        prev_close = start_close
        for day_key in day_keys:
            opens, highs, lows, closes, vols, _ois, _regime = self._day_path(symbol, day_key, prev_close)
            rows_1m = self._candle_dicts(symbol, "1m", opens, highs, lows, closes, vols, 375, day_key)
            yield "1m", rows_1m
            yield "5m", self._aggregate(rows_1m, 5)
            yield "15m", self._aggregate(rows_1m, 15)
            prev_close = float(closes[-1])

    # ---------------- option chain ----------------

    def get_option_chain(self, symbol: str) -> ChainSnapshot:
        """Interface method — default-anchored chain. Engines call build_chain with a quote."""
        quote = self.get_quote(symbol, self.live_anchor(symbol, None))
        return self.build_chain(symbol, quote)

    def next_expiries(self, symbol: str, ist_now: datetime | None = None) -> list[str]:
        """Contract expiry dates (YYYY-MM-DD), nearest first. NIFTY: 3 weeklies + monthly."""
        inst = INSTRUMENTS[symbol]
        now = ist_now or datetime.now(IST)
        out: list[str] = []
        if inst.weekly_expiries:
            d = now.date()
            offset = (3 - d.weekday()) % 7  # Thursday
            for k in range(3):
                out.append((d + timedelta(days=offset + 7 * k)).isoformat())
        # monthlies: last Thursday of this and next month
        for month_offset in (0, 1):
            y, mth = now.year, now.month + month_offset
            if mth > 12:
                y, mth = y + 1, mth - 12
            nxt = date(y + (1 if mth == 12 else 0), 1 if mth == 12 else mth + 1, 1)
            last_day = nxt - timedelta(days=1)
            while last_day.weekday() != 3:
                last_day -= timedelta(days=1)
            if last_day.isoformat() not in out:
                out.append(last_day.isoformat())
        return sorted(out)[:4]

    def _iv_for(self, spot: float, strike: float, t_years: float, call: bool, regime: str) -> float:
        base = {"trend_up": 0.115, "trend_down": 0.145, "range": 0.105,
                "high_vol": 0.21, "low_vol": 0.085}[regime]
        moneyness = math.log(strike / spot)
        smile = 3.2 * moneyness * moneyness
        skew = 0.008 if (not call and strike < spot) else 0.0
        term = 0.01 if t_years < 3 / 365 else 0.0
        return round(max(0.05, base + smile + skew + term), 4)

    def build_chain(self, symbol: str, quote: Quote, ist_now: datetime | None = None) -> ChainSnapshot:
        inst = INSTRUMENTS[symbol]
        now = ist_now or datetime.now(IST)
        spot = quote.ltp
        regime = quote.regime
        atm = round(spot / inst.strike_step) * inst.strike_step
        snap = ChainSnapshot(underlying=symbol, spot=spot, atm_strike=atm,
                             ts=quote.ts, regime=regime)
        # futures leg
        fut_t = 12 / 365
        snap.futures_price = round(spot * (1 + 0.065 * fut_t) , 2)
        snap.basis = round(snap.futures_price - spot, 2)
        rng = _seed_rng("fno", symbol, quote.ts.strftime("%Y%m%d%H"))
        snap.fut_oi_change = int(rng.normal(0.002 if regime == "trend_up" else -0.002 if regime == "trend_down" else 0, 0.01) * inst.base_volume * 8)

        prev_oi_map = self._last_oi.get(symbol, {})
        new_oi_map: dict[tuple, int] = {}
        strikes = [atm + i * inst.strike_step for i in range(-10, 11)]
        total_ce_oi = total_pe_oi = 0.0
        for expiry in self.next_expiries(symbol, now):
            exp_dt = datetime.fromisoformat(expiry).replace(hour=15, minute=30, tzinfo=IST)
            t_years = max((exp_dt - now).total_seconds(), 3600) / (365 * 24 * 3600)
            e_rng = _seed_rng("chain", symbol, expiry, quote.ts.strftime("%Y%m%d"))
            exp_mult = 1.4 if expiry == self.next_expiries(symbol, now)[0] else 1.0  # nearest expiry carries the most liquidity
            for strike in strikes:
                for call in (True, False):
                    otm_dist = (strike - atm) if call else (atm - strike)
                    iv = self._iv_for(spot, strike, t_years, call, regime)
                    price = float(option_math.bs_price(spot, strike, t_years, iv, call))
                    # liquidity profile: OI peaks near ATM and round strikes, decays for far OTM
                    round_bonus = 1.6 if strike % (inst.strike_step * 4) == 0 else 1.0
                    if call:
                        oi_shape = math.exp(-max(0.0, strike - atm) ** 2 / (2 * (3.2 * inst.strike_step) ** 2))
                    else:
                        oi_shape = math.exp(-max(0.0, atm - strike) ** 2 / (2 * (3.2 * inst.strike_step) ** 2))
                    near_atm = math.exp(-((strike - atm) / (2.2 * inst.strike_step)) ** 2)
                    oi_base = inst.base_volume * (0.9 * oi_shape + 1.5 * near_atm) * round_bonus * exp_mult
                    oi = int(max(50, oi_base * float(e_rng.uniform(0.6, 1.5))))
                    # regime-aligned OI build-up: bulls write puts / shorts write calls
                    if regime == "trend_up":
                        oi_change = int(oi * (0.10 if not call else -0.06) * float(e_rng.uniform(0.4, 1.6)))
                    elif regime == "trend_down":
                        oi_change = int(oi * (0.10 if call else -0.06) * float(e_rng.uniform(0.4, 1.6)))
                    else:
                        oi_change = int(oi * 0.03 * float(e_rng.uniform(-1.5, 1.5)))
                    activity = near_atm * 0.9 + 0.06
                    volume = int(oi * activity * float(e_rng.uniform(0.5, 1.7)) / (1 + abs(strike - atm) / (4 * inst.strike_step)))
                    # spread widens for far strikes & low activity; some contracts deliberately illiquid
                    liq = (volume / max(oi, 1) ) * near_atm
                    spread_pct = min(0.045, max(0.0008, 0.0012 + 0.05 * (1 - min(liq * 3, 1)) * (abs(strike - atm) / (6 * inst.strike_step) + 0.12)))
                    half = price * spread_pct / 2
                    if call:
                        total_ce_oi += oi
                    else:
                        total_pe_oi += oi
                    key = (expiry, strike, "CE" if call else "PE")
                    change = oi_change if key not in prev_oi_map else int(oi - prev_oi_map[key])
                    moneyness = "ATM" if strike == atm else ("ITM" if (strike < spot) == call else "OTM")
                    delta, gamma, theta, vega = option_math.bs_greeks(spot, strike, t_years, iv, call)
                    snap.rows.append(OptionRow(
                        underlying=symbol, expiry=expiry, strike=float(strike),
                        option_type="CE" if call else "PE",
                        ltp=round(price, 2),
                        bid=round(max(price - half, 0.05), 2),
                        ask=round(price + half, 2),
                        volume=volume, open_interest=oi, change_in_oi=change,
                        iv=iv, delta=round(delta, 3), gamma=round(gamma, 6),
                        theta=round(theta, 2), vega=round(vega, 2),
                        moneyness=moneyness, ts=quote.ts,
                    ))
                    new_oi_map[key] = oi
        self._last_oi[symbol] = new_oi_map
        snap.pcr = round(total_pe_oi / max(total_ce_oi, 1), 3)
        snap.max_pain = self._max_pain(snap.rows, strikes)
        return snap

    @staticmethod
    def _max_pain(rows: list[OptionRow], strikes: list[float]) -> float:
        ce_oi = {r.strike: r.open_interest for r in rows if r.option_type == "CE"}
        pe_oi = {r.strike: r.open_interest for r in rows if r.option_type == "PE"}
        best, best_pain = strikes[0], None
        for s in strikes:
            pain = sum(oi * max(0.0, s - k) for k, oi in ce_oi.items()) + \
                   sum(oi * max(0.0, k - s) for k, oi in pe_oi.items())
            if best_pain is None or pain < best_pain:
                best_pain, best = pain, s
        return float(best)

    # ---------------- historical/backtest repricing ----------------

    def price_option(self, spot: float, strike: float, t_years: float, iv: float,
                     call: bool) -> float:
        return float(option_math.bs_price(spot, strike, max(t_years, 1e-6), iv, call))

    def backtest_chain(self, symbol: str, spot: float, day_key: str, ts_utc: datetime,
                       expiry: str, regime: str, strikes_per_side: int = 10) -> ChainSnapshot:
        """Deterministic synthetic chain at a historical timestamp (backtest input, 36.7)."""
        inst = INSTRUMENTS[symbol]
        atm = round(spot / inst.strike_step) * inst.strike_step
        snap = ChainSnapshot(underlying=symbol, spot=spot, atm_strike=atm, ts=ts_utc, regime=regime)
        exp_dt = datetime.fromisoformat(expiry).replace(hour=15, minute=30, tzinfo=IST)
        now = ts_utc.astimezone(IST)
        t_years = max((exp_dt - now).total_seconds(), 3600) / (365 * 24 * 3600)
        e_rng = _seed_rng("chain", symbol, expiry, day_key)
        strikes = [atm + i * inst.strike_step for i in range(-strikes_per_side, strikes_per_side + 1)]
        total_ce = total_pe = 0.0
        for strike in strikes:
            for call in (True, False):
                iv = self._iv_for(spot, strike, t_years, call, regime)
                price = float(option_math.bs_price(spot, strike, t_years, iv, call))
                near_atm = math.exp(-((strike - atm) / (2.2 * inst.strike_step)) ** 2)
                round_bonus = 1.6 if strike % (inst.strike_step * 4) == 0 else 1.0
                oi_shape = math.exp(-max(0.0, (strike - atm) if call else (atm - strike)) ** 2 / (2 * (3.2 * inst.strike_step) ** 2))
                oi = int(inst.base_volume * (0.9 * oi_shape + 1.5 * near_atm) * round_bonus * float(e_rng.uniform(0.6, 1.5)))
                if regime == "trend_up":
                    oi_change = int(oi * (0.10 if not call else -0.06) * float(e_rng.uniform(0.4, 1.6)))
                elif regime == "trend_down":
                    oi_change = int(oi * (0.10 if call else -0.06) * float(e_rng.uniform(0.4, 1.6)))
                else:
                    oi_change = int(oi * 0.03 * float(e_rng.uniform(-1.5, 1.5)))
                activity = near_atm * 0.9 + 0.06
                volume = int(oi * activity * float(e_rng.uniform(0.5, 1.7)) / (1 + abs(strike - atm) / (4 * inst.strike_step)))
                liq = (volume / max(oi, 1)) * near_atm
                spread_pct = min(0.045, max(0.0008, 0.0012 + 0.05 * (1 - min(liq * 3, 1)) * (abs(strike - atm) / (6 * inst.strike_step) + 0.12)))
                half = price * spread_pct / 2
                if call:
                    total_ce += oi
                else:
                    total_pe += oi
                moneyness = "ATM" if strike == atm else ("ITM" if (strike < spot) == call else "OTM")
                delta, gamma, theta, vega = option_math.bs_greeks(spot, strike, t_years, iv, call)
                snap.rows.append(OptionRow(
                    underlying=symbol, expiry=expiry, strike=float(strike),
                    option_type="CE" if call else "PE", ltp=round(price, 2),
                    bid=round(max(price - half, 0.05), 2), ask=round(price + half, 2),
                    volume=volume, open_interest=oi, change_in_oi=oi_change, iv=iv,
                    delta=round(delta, 3), gamma=round(gamma, 6), theta=round(theta, 2),
                    vega=round(vega, 2), moneyness=moneyness, ts=ts_utc,
                ))
        snap.pcr = round(total_pe / max(total_ce, 1), 3)
        snap.max_pain = self._max_pain(snap.rows, strikes)
        snap.futures_price = round(spot * (1 + 0.065 * 12 / 365), 2)
        snap.basis = round(snap.futures_price - spot, 2)
        rng = _seed_rng("fno", symbol, day_key)
        snap.fut_oi_change = int(rng.normal(0, 0.01) * inst.base_volume * 8)
        return snap

    def chain_summary(self, symbol: str, spot: float, day_key: str, ts_utc: datetime,
                      expiry: str, regime: str) -> ChainSnapshot:
        """Cheap F&O summary (PCR, max pain, futures/basis, ΔOI) with NO option pricing.

        The direction engine only reads these aggregates, so the backtester uses this on
        every candle and pays for a full priced chain solely when a signal qualifies.
        """
        inst = INSTRUMENTS[symbol]
        atm = round(spot / inst.strike_step) * inst.strike_step
        snap = ChainSnapshot(underlying=symbol, spot=spot, atm_strike=atm, ts=ts_utc, regime=regime)
        e_rng = _seed_rng("chain", symbol, expiry, day_key)
        strikes = [atm + i * inst.strike_step for i in range(-10, 11)]
        total_ce = total_pe = 0.0
        ce_oi: dict[float, int] = {}
        pe_oi: dict[float, int] = {}
        for strike in strikes:
            for call in (True, False):
                near_atm = math.exp(-((strike - atm) / (2.2 * inst.strike_step)) ** 2)
                round_bonus = 1.6 if strike % (inst.strike_step * 4) == 0 else 1.0
                oi_shape = math.exp(-max(0.0, (strike - atm) if call else (atm - strike)) ** 2 / (2 * (3.2 * inst.strike_step) ** 2))
                oi = int(inst.base_volume * (0.9 * oi_shape + 1.5 * near_atm) * round_bonus * float(e_rng.uniform(0.6, 1.5)))
                if call:
                    total_ce += oi
                    ce_oi[strike] = oi
                else:
                    total_pe += oi
                    pe_oi[strike] = oi
        snap.pcr = round(total_pe / max(total_ce, 1), 3)
        best, best_pain = strikes[0], None
        for s in strikes:
            pain = sum(oi * max(0.0, s - k) for k, oi in ce_oi.items()) + \
                   sum(oi * max(0.0, k - s) for k, oi in pe_oi.items())
            if best_pain is None or pain < best_pain:
                best_pain, best = pain, s
        snap.max_pain = float(best)
        snap.futures_price = round(spot * (1 + 0.065 * 12 / 365), 2)
        snap.basis = round(snap.futures_price - spot, 2)
        rng = _seed_rng("fno", symbol, day_key)
        snap.fut_oi_change = int(rng.normal(0.002 if regime == "trend_up" else -0.002 if regime == "trend_down" else 0, 0.01) * inst.base_volume * 8)
        return snap

    def iv_for_backtest(self, spot: float, strike: float, t_years: float, call: bool,
                        regime: str) -> float:
        return self._iv_for(spot, strike, t_years, call, regime)


def UTC_naive_guard():
    """datetime.now(UTC) helper kept as a function to avoid import cycles."""
    from lib.dates import UTC

    return UTC


def session_minute_to_utc(day_key: str, minute_index: int) -> datetime:
    """UTC datetime of a session minute's candle OPEN. Real dates map to their true
    IST time; sim day keys map onto today's real date (feed-managed)."""
    from lib.dates import UTC, now_ist

    if day_key.startswith("sim-"):
        base = now_ist().replace(hour=9, minute=15, second=0, microsecond=0)
    else:
        base = datetime.strptime(day_key, "%Y-%m-%d").replace(hour=9, minute=15, tzinfo=IST)
    return (base + timedelta(minutes=minute_index)).astimezone(UTC)
