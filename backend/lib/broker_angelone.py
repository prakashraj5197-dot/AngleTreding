"""Angel One SmartAPI live market-data adapter.

Sits behind the same surface the simulator implements, so the engines never learn which
vendor is attached (spec §2: provider integration stays isolated behind an interface).

Credentials live ONLY in backend/.env and are never returned by any route (AC-75):
    ANGELONE_API_KEY, ANGELONE_CLIENT_CODE, ANGELONE_MPIN, ANGELONE_TOTP_SECRET

What this adapter overrides (the live paths):
    get_status, get_quote, today_candles, get_candles, next_expiries, build_chain, live_anchor

What it inherits from SimulatedProvider (deliberately):
    backtest_chain / chain_summary / iv_for_backtest / price_option / _regime_for.
    Backtests replay STORED candles and reprice options with Black-Scholes, which is
    vendor-independent — a live feed changes where today's data comes from, not how
    history is replayed.

Design notes anchored in the SmartAPI docs:
  • Auth is generateSession(client_code, mpin, TOTP) → jwtToken + refreshToken. Sessions are
    day-scoped, so we re-login on AG8001/AG8002/AB1010/AB8050 and after a stale-session age.
  • There is NO option-chain REST endpoint carrying IV or greeks. We build the chain from
    the instrument master, quote the contracts in FULL mode (which does carry openInterest
    and bid/ask depth for derivatives) and then solve IV from the premium with Black-Scholes
    and derive greeks locally. This is recorded honestly as a derived field, never presented
    as vendor data.
  • Quote limits are 10 req/s, 500/min, 5000/hr and FULL mode accepts up to 50 tokens per
    call, so a chain sweep is chunked and cached for the configured freshness window.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import threading
import time as _time
from datetime import datetime, timedelta

import httpx

from lib import option_math
from lib.dates import IST, SESSION_SECONDS, UTC, ist_date, now_ist
from lib.sim_provider import (
    INSTRUMENTS,
    ChainSnapshot,
    MarketStatusInfo,
    OptionRow,
    Quote,
    SimulatedProvider,
)

logger = logging.getLogger("quantpulse.angelone")

SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

# SmartAPI session/auth failures that mean "log in again" rather than "data problem"
AUTH_ERROR_CODES = {"AG8001", "AG8002", "AB8050", "AB1010", "AB8051"}

INTERVAL_MAP = {"1m": "ONE_MINUTE", "5m": "FIVE_MINUTE", "15m": "FIFTEEN_MINUTE"}
# NSE index spot tokens are stable, but we still resolve from the master and use these
# only as a fallback if the dump shape changes.
INDEX_TOKEN_FALLBACK = {"NIFTY": "99926000", "BANKNIFTY": "99926009"}
MAX_TOKENS_PER_QUOTE = 50


class ProviderUnavailable(RuntimeError):
    """Raised when the live feed cannot be trusted. Callers must fail safe, never guess."""


def credentials_present() -> bool:
    return all(
        os.environ.get(k)
        for k in ("ANGELONE_API_KEY", "ANGELONE_CLIENT_CODE", "ANGELONE_MPIN", "ANGELONE_TOTP_SECRET")
    )


def missing_credentials() -> list[str]:
    return [
        k
        for k in ("ANGELONE_API_KEY", "ANGELONE_CLIENT_CODE", "ANGELONE_MPIN", "ANGELONE_TOTP_SECRET")
        if not os.environ.get(k)
    ]


class AngelOneProvider(SimulatedProvider):
    """Live NSE/NFO data via Angel One SmartAPI."""

    name = "angelone"

    def __init__(self) -> None:
        super().__init__()
        self.session_mode = "market_hours"  # a real exchange feed is never "always on"
        self._api = None
        self._logged_in_at: float = 0.0
        self._login_lock = threading.Lock()
        self.last_error: str | None = None
        self.last_login_ist: str | None = None
        # instrument master
        self._instruments_day: str | None = None
        self._index_tokens: dict[str, str] = {}
        self._options: dict[str, list[dict]] = {}  # symbol -> option instrument rows
        # caches keyed by freshness
        self._quote_cache: dict[str, tuple[float, Quote]] = {}
        self._chain_cache: dict[str, tuple[float, ChainSnapshot]] = {}
        self._prev_oi: dict[tuple, int] = {}

    # ------------------------------------------------------------------ session

    def _connect(self, force: bool = False):
        """Return a logged-in SmartConnect, logging in if needed. Thread-safe."""
        if not credentials_present():
            raise ProviderUnavailable(
                "Angel One credentials are not configured. Set "
                + ", ".join(missing_credentials())
                + " in backend/.env and restart the backend."
            )
        with self._login_lock:
            fresh = self._api is not None and (_time.monotonic() - self._logged_in_at) < 6 * 3600
            if fresh and not force:
                return self._api
            try:
                from SmartApi import SmartConnect  # imported lazily: optional dependency
                import pyotp
            except Exception as exc:  # pragma: no cover - import guard
                raise ProviderUnavailable(f"SmartAPI SDK is not installed: {exc}") from exc

            api = SmartConnect(api_key=os.environ["ANGELONE_API_KEY"])
            try:
                totp = pyotp.TOTP(os.environ["ANGELONE_TOTP_SECRET"].strip()).now()
            except Exception as exc:
                raise ProviderUnavailable(
                    "ANGELONE_TOTP_SECRET is not a valid base32 TOTP secret — copy the secret "
                    f"string shown when enabling 2FA (not the 6-digit code). ({exc})"
                ) from exc

            try:
                res = api.generateSession(
                    os.environ["ANGELONE_CLIENT_CODE"].strip(),
                    os.environ["ANGELONE_MPIN"].strip(),
                    totp,
                )
            except Exception as exc:
                self.last_error = f"login transport error: {exc}"
                raise ProviderUnavailable(self.last_error) from exc

            if not isinstance(res, dict) or not res.get("status"):
                msg = (res or {}).get("message") or "unknown error"
                code = (res or {}).get("errorcode", "")
                self.last_error = f"login rejected by Angel One: {msg} ({code})"
                raise ProviderUnavailable(self.last_error)

            self._api = api
            self._logged_in_at = _time.monotonic()
            self.last_login_ist = now_ist().strftime("%Y-%m-%d %H:%M:%S")
            self.last_error = None
            logger.info("Angel One session established for %s", os.environ["ANGELONE_CLIENT_CODE"])
            return api

    def _call(self, method: str, *args, **kwargs):
        """Invoke an SDK method, re-logging in once on an auth-class error."""
        api = self._connect()
        for attempt in (1, 2):
            try:
                res = getattr(api, method)(*args, **kwargs)
            except Exception as exc:
                self.last_error = f"{method} transport error: {exc}"
                raise ProviderUnavailable(self.last_error) from exc
            if isinstance(res, dict) and not res.get("status"):
                code = str(res.get("errorcode", ""))
                msg = res.get("message") or "request failed"
                if code in AUTH_ERROR_CODES and attempt == 1:
                    logger.warning("Angel One session expired (%s) — re-authenticating", code)
                    api = self._connect(force=True)
                    continue
                self.last_error = f"{method}: {msg} ({code})"
                raise ProviderUnavailable(self.last_error)
            return res
        raise ProviderUnavailable(self.last_error or f"{method} failed")

    def login_check(self) -> dict:
        """Used by the admin 'test connection' route. Never returns secret values."""
        try:
            self._connect(force=True)
            self.load_instruments(force=True)
            counts = {s: len(v) for s, v in self._options.items()}
            return {
                "ok": True,
                "message": "Angel One session established and instrument master loaded.",
                "client_code_masked": _mask(os.environ.get("ANGELONE_CLIENT_CODE", "")),
                "last_login_ist": self.last_login_ist,
                "index_tokens": self._index_tokens,
                "option_contracts": counts,
            }
        except ProviderUnavailable as exc:
            return {"ok": False, "message": str(exc), "missing_env": missing_credentials()}

    # --------------------------------------------------------- instrument master

    def load_instruments(self, force: bool = False) -> None:
        """Download + filter the daily scrip master (refreshed once per IST day)."""
        today = ist_date()
        if not force and self._instruments_day == today and self._index_tokens:
            return
        try:
            with httpx.Client(timeout=90) as client:
                rows = client.get(SCRIP_MASTER_URL).json()
        except Exception as exc:
            if self._index_tokens:  # keep yesterday's map rather than going blind
                logger.warning("scrip master refresh failed, keeping cached map: %s", exc)
                return
            raise ProviderUnavailable(f"could not download the instrument master: {exc}") from exc

        wanted = set(INSTRUMENTS.keys())
        index_tokens: dict[str, str] = {}
        options: dict[str, list[dict]] = {s: [] for s in wanted}
        for r in rows:
            name = (r.get("name") or "").upper()
            if name not in wanted:
                continue
            seg = (r.get("exch_seg") or "").upper()
            itype = (r.get("instrumenttype") or "").upper()
            if seg == "NSE" and (r.get("symbol") or "").upper() == name:
                index_tokens[name] = str(r.get("token"))
            elif seg == "NFO" and itype == "FUTIDX":
                expiry = _parse_expiry(r.get("expiry") or "")
                if expiry:
                    options.setdefault(f"{name}__FUT", []).append({
                        "token": str(r.get("token")), "symbol": (r.get("symbol") or "").upper(),
                        "expiry": expiry, "strike": 0.0, "option_type": "FUT",
                        "lotsize": int(r.get("lotsize") or INSTRUMENTS[name].lot_size),
                    })
            elif seg == "NFO" and itype == "OPTIDX":
                expiry = _parse_expiry(r.get("expiry") or "")
                if not expiry:
                    continue
                sym = (r.get("symbol") or "").upper()
                if sym.endswith("CE"):
                    otype = "CE"
                elif sym.endswith("PE"):
                    otype = "PE"
                else:
                    continue
                try:
                    strike = float(r.get("strike") or 0) / 100.0  # master stores paise
                except (TypeError, ValueError):
                    continue
                if strike <= 0:
                    continue
                options[name].append({
                    "token": str(r.get("token")), "symbol": sym, "expiry": expiry,
                    "strike": strike, "option_type": otype,
                    "lotsize": int(r.get("lotsize") or INSTRUMENTS[name].lot_size),
                })

        for sym in wanted:
            if sym not in index_tokens and sym in INDEX_TOKEN_FALLBACK:
                index_tokens[sym] = INDEX_TOKEN_FALLBACK[sym]
        self._index_tokens = index_tokens
        self._options = options
        self._instruments_day = today

        # The exchange revises lot sizes (NIFTY has moved 75 → 65); trust the broker's
        # instrument master over our static table so live position sizing stays correct.
        for sym in ("NIFTY", "BANKNIFTY"):
            rows = options.get(sym) or []
            if not rows:
                continue
            sizes: dict[int, int] = {}
            for r in rows:
                sizes[r["lotsize"]] = sizes.get(r["lotsize"], 0) + 1
            lot = max(sizes.items(), key=lambda kv: kv[1])[0]
            if lot > 0 and INSTRUMENTS[sym].lot_size != lot:
                logger.info("lot size for %s updated from broker master: %s → %s",
                            sym, INSTRUMENTS[sym].lot_size, lot)
                INSTRUMENTS[sym] = dataclasses.replace(INSTRUMENTS[sym], lot_size=lot)
        logger.info(
            "instrument master loaded: indices=%s options=%s",
            index_tokens, {k: len(v) for k, v in options.items()},
        )

    # ------------------------------------------------------------------- status

    def get_status(self) -> MarketStatusInfo:
        now = now_ist()
        elapsed = int((now - now.replace(hour=9, minute=15, second=0, microsecond=0)).total_seconds())
        weekday = now.weekday() < 5
        is_open = weekday and 0 <= elapsed <= SESSION_SECONDS
        note = "Angel One SmartAPI live feed (NSE/NFO)."
        if not weekday:
            note = "Weekend — NSE equity derivatives session is closed."
        elif elapsed < 0:
            note = "Pre-market — normal session starts at 09:15 IST."
        elif elapsed > SESSION_SECONDS:
            note = "Post-market — normal session closed at 15:30 IST."
        return MarketStatusInfo(
            status="OPEN" if is_open else "CLOSED",
            ist_time=now.strftime("%H:%M:%S"),
            ist_date=now.strftime("%Y-%m-%d"),
            session_elapsed=max(0, min(elapsed, SESSION_SECONDS)),
            session_mode="market_hours",
            simulated=False,
            note=note,
        )

    # -------------------------------------------------------------------- quote

    def _quote_full(self, exchange: str, tokens: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(tokens), MAX_TOKENS_PER_QUOTE):
            chunk = tokens[i:i + MAX_TOKENS_PER_QUOTE]
            res = self._call("getMarketData", "FULL", {exchange: chunk})
            data = (res or {}).get("data") or {}
            out.extend(data.get("fetched") or [])
            if (i + MAX_TOKENS_PER_QUOTE) < len(tokens):
                _time.sleep(0.12)  # stay inside the 10 req/s quote budget
        return out

    def get_quote(self, symbol: str, anchor_close: float | None = None,
                  ist_now: datetime | None = None) -> Quote:
        cached = self._quote_cache.get(symbol)
        if cached and (_time.monotonic() - cached[0]) < 1.0:
            return cached[1]
        self.load_instruments()
        token = self._index_tokens.get(symbol)
        if not token:
            raise ProviderUnavailable(f"no Angel One token found for {symbol}")
        rows = self._quote_full("NSE", [token])
        if not rows:
            raise ProviderUnavailable(f"Angel One returned no quote for {symbol}")
        r = rows[0]
        status = self.get_status()
        ltp = _f(r.get("ltp"))
        prev_close = _f(r.get("close")) or ltp
        ts = _parse_feed_time(r.get("exchFeedTime")) or datetime.now(UTC)
        quote = Quote(
            symbol=symbol,
            ltp=round(ltp, 2),
            open=round(_f(r.get("open")) or ltp, 2),
            high=round(_f(r.get("high")) or ltp, 2),
            low=round(_f(r.get("low")) or ltp, 2),
            prev_close=round(prev_close, 2),
            volume=_f(r.get("tradeVolume")),
            vwap=round(_f(r.get("avgPrice")) or ltp, 2),
            change=round(_f(r.get("netChange")) or (ltp - prev_close), 2),
            change_pct=round(_f(r.get("percentChange")) or 0.0, 2),
            ts=ts,
            market_status=status.status,
            session_elapsed=status.session_elapsed,
            session_mode="market_hours",
            simulated=False,
            regime="range",
        )
        self._quote_cache[symbol] = (_time.monotonic(), quote)
        return quote

    def live_anchor(self, symbol: str, last_stored_close: float | None) -> float:
        """Live feed needs no synthetic anchor — the vendor is the source of truth."""
        return float(last_stored_close or 0.0)

    # ------------------------------------------------------------------ candles

    def get_candles(self, symbol: str, timeframe: str, frm: datetime, to: datetime,
                    exchange: str = "NSE", token: str | None = None) -> list[dict]:
        self.load_instruments()
        tok = token or self._index_tokens.get(symbol)
        if not tok:
            raise ProviderUnavailable(f"no Angel One token found for {symbol}")
        res = self._call("getCandleData", {
            "exchange": exchange,
            "symboltoken": tok,
            "interval": INTERVAL_MAP[timeframe],
            "fromdate": frm.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
            "todate": to.astimezone(IST).strftime("%Y-%m-%d %H:%M"),
        })
        out: list[dict] = []
        for row in (res or {}).get("data") or []:
            # [timestamp, o, h, l, c, v] with an ISO timestamp carrying +05:30
            try:
                ts = datetime.fromisoformat(row[0]).astimezone(UTC)
            except Exception:
                continue
            out.append({
                "symbol": symbol, "timeframe": timeframe, "ts": ts,
                "o": float(row[1]), "h": float(row[2]), "l": float(row[3]),
                "c": float(row[4]), "v": float(row[5]), "oi": None,
            })
        return out

    def today_candles(self, symbol: str, anchor_close: float | None = None,
                      timeframe: str = "1m") -> list[dict]:
        """Today's session candles straight from the vendor (used to top up storage)."""
        now = now_ist()
        start = now.replace(hour=9, minute=15, second=0, microsecond=0)
        if now < start:
            return []
        try:
            return self.get_candles(symbol, timeframe, start, now)
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise ProviderUnavailable(f"candle fetch failed for {symbol}: {exc}") from exc

    # -------------------------------------------------------------- option chain

    def next_expiries(self, symbol: str, ist_now: datetime | None = None) -> list[str]:
        """Real listed expiries from the instrument master, not a weekday guess."""
        self.load_instruments()
        today = (ist_now or now_ist()).strftime("%Y-%m-%d")
        expiries = sorted({o["expiry"] for o in self._options.get(symbol, []) if o["expiry"] >= today})
        return expiries[:4]

    def build_chain(self, symbol: str, quote: Quote, ist_now: datetime | None = None) -> ChainSnapshot:
        cached = self._chain_cache.get(symbol)
        if cached and (_time.monotonic() - cached[0]) < 10.0:
            return cached[1]
        self.load_instruments()
        inst = INSTRUMENTS[symbol]
        spot = quote.ltp
        atm = round(spot / inst.strike_step) * inst.strike_step
        expiries = self.next_expiries(symbol, ist_now)[:2]
        if not expiries:
            raise ProviderUnavailable(f"no live option expiries listed for {symbol}")

        window = 10 * inst.strike_step
        wanted = [
            o for o in self._options.get(symbol, [])
            if o["expiry"] in expiries and abs(o["strike"] - atm) <= window
        ]
        if not wanted:
            raise ProviderUnavailable(f"no option contracts near ATM {atm} for {symbol}")

        by_token = {o["token"]: o for o in wanted}
        rows_raw = self._quote_full("NFO", list(by_token.keys()))
        now_utc_dt = datetime.now(UTC)
        snap = ChainSnapshot(underlying=symbol, spot=spot, atm_strike=float(atm),
                             ts=now_utc_dt, regime=quote.regime)

        total_ce = total_pe = 0.0
        ce_oi: dict[float, int] = {}
        pe_oi: dict[float, int] = {}
        for r in rows_raw:
            meta = by_token.get(str(r.get("symbolToken")))
            if not meta:
                continue
            ltp = _f(r.get("ltp"))
            if ltp <= 0:
                continue
            bid, ask = _best_bid_ask(r)
            oi = int(_f(r.get("opnInterest")))
            key = (symbol, meta["expiry"], meta["strike"], meta["option_type"])
            prev = self._prev_oi.get(key)
            self._prev_oi[key] = oi
            exp_dt = datetime.fromisoformat(meta["expiry"]).replace(hour=15, minute=30, tzinfo=IST)
            t_years = max((exp_dt - now_ist()).total_seconds(), 3600) / (365 * 24 * 3600)
            call = meta["option_type"] == "CE"
            # IV and greeks are DERIVED locally — SmartAPI does not publish them
            # IV and greeks are DERIVED locally — SmartAPI does not publish them.
            # An unsolvable premium (outside arbitrage bounds / stale book) yields iv=0 and
            # zero greeks rather than an invented number: the engine's IV-window scoring
            # then deprioritises the contract instead of trusting a guess (AC-72).
            iv = option_math.implied_vol(ltp, spot, meta["strike"], t_years, call)
            if iv is None:
                iv = 0.0
                delta = gamma = theta = vega = 0.0
            else:
                delta, gamma, theta, vega = option_math.bs_greeks(
                    spot, meta["strike"], t_years, iv, call)
            if abs(meta["strike"] - atm) < inst.strike_step / 2:
                moneyness = "ATM"
            elif (call and meta["strike"] < spot) or (not call and meta["strike"] > spot):
                moneyness = "ITM"
            else:
                moneyness = "OTM"
            snap.rows.append(OptionRow(
                underlying=symbol, expiry=meta["expiry"], strike=float(meta["strike"]),
                option_type=meta["option_type"], ltp=round(ltp, 2),
                bid=round(bid, 2), ask=round(ask, 2),
                volume=int(_f(r.get("tradeVolume"))), open_interest=oi,
                change_in_oi=int(oi - prev) if prev is not None else 0,
                iv=round(float(iv), 4), delta=round(delta, 4), gamma=round(gamma, 6),
                theta=round(theta, 3), vega=round(vega, 3),
                moneyness=moneyness, ts=now_utc_dt,
            ))
            if call:
                total_ce += oi
                ce_oi[meta["strike"]] = ce_oi.get(meta["strike"], 0) + oi
            else:
                total_pe += oi
                pe_oi[meta["strike"]] = pe_oi.get(meta["strike"], 0) + oi

        if not snap.rows:
            raise ProviderUnavailable(f"live option chain for {symbol} came back empty")

        snap.pcr = round(total_pe / max(total_ce, 1), 3)
        strikes = sorted(set(ce_oi) | set(pe_oi))
        best, best_pain = float(atm), None
        for s in strikes:
            pain = sum(o * max(0.0, s - k) for k, o in ce_oi.items()) + \
                   sum(o * max(0.0, k - s) for k, o in pe_oi.items())
            if best_pain is None or pain < best_pain:
                best_pain, best = pain, float(s)
        snap.max_pain = best
        fut = self._futures_quote(symbol, expiries[0])
        snap.futures_price = fut[0] if fut else 0.0
        snap.basis = round(snap.futures_price - spot, 2) if fut else 0.0
        snap.fut_oi_change = fut[1] if fut else 0
        self._chain_cache[symbol] = (_time.monotonic(), snap)
        return snap

    def _futures_quote(self, symbol: str, expiry: str) -> tuple[float, int] | None:
        """Nearest-month future for basis/OI, best-effort (absent ⇒ basis reported as 0)."""
        try:
            fut = [
                o for o in self._options.get(f"{symbol}__FUT", [])
                if o["expiry"] == expiry
            ]
            if not fut:
                return None
            rows = self._quote_full("NFO", [fut[0]["token"]])
            if not rows:
                return None
            return round(_f(rows[0].get("ltp")), 2), int(_f(rows[0].get("opnInterest")))
        except ProviderUnavailable:
            return None


# --------------------------------------------------------------------- helpers


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _mask(v: str) -> str:
    return f"{v[:2]}{'•' * max(0, len(v) - 4)}{v[-2:]}" if len(v) > 4 else "••••"


def _parse_expiry(raw: str) -> str | None:
    """'25SEP2025' → '2025-09-25'."""
    try:
        return datetime.strptime(raw.strip().upper(), "%d%b%Y").strftime("%Y-%m-%d")
    except Exception:
        return None


def _parse_feed_time(raw) -> datetime | None:
    """exchFeedTime is either epoch-ish or 'dd-Mon-yyyy HH:MM:SS' depending on endpoint."""
    if raw in (None, "", 0):
        return None
    if isinstance(raw, (int, float)) or str(raw).isdigit():
        val = float(raw)
        if val > 1e11:
            val /= 1000.0
        try:
            return datetime.fromtimestamp(val, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(str(raw), fmt).replace(tzinfo=IST).astimezone(UTC)
        except ValueError:
            continue
    return None


def _best_bid_ask(r: dict) -> tuple[float, float]:
    depth = r.get("depth") or {}
    buy = depth.get("buy") or []
    sell = depth.get("sell") or []
    ltp = _f(r.get("ltp"))
    bid = _f(buy[0].get("price")) if buy else 0.0
    ask = _f(sell[0].get("price")) if sell else 0.0
    # a closed/illiquid book returns zeros — fall back to LTP so spread filters stay honest
    return (bid or ltp), (ask or ltp)
