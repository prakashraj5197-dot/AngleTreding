"""Technical indicators — numpy, causal (value at index i uses data <= i only).

All functions accept plain float lists or numpy arrays and return numpy arrays of the
same length. Warm-up values are np.nan so callers can filter them explicitly; nothing
is silently substituted (spec AC-72).
"""

from typing import Literal

import numpy as np


def _as_np(values) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return arr


def ema(values, period: int) -> np.ndarray:
    """Exponential moving average (seeded with SMA of the first `period` values)."""
    arr = _as_np(values)
    out = np.full(arr.shape, np.nan)
    if arr.size < period:
        return out
    alpha = 2.0 / (period + 1.0)
    seed = arr[:period].mean()
    out[period - 1] = seed
    for i in range(period, arr.size):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def sma(values, period: int) -> np.ndarray:
    arr = _as_np(values)
    out = np.full(arr.shape, np.nan)
    if arr.size < period:
        return out
    csum = np.cumsum(arr)
    out[period - 1 :] = (csum[period - 1 :] - np.concatenate(([0.0], csum[:-period]))) / period
    return out


def vwap(high, low, close, volume, session_ids) -> np.ndarray:
    """Session-anchored VWAP: resets at every change of `session_ids` (per-day).

    `session_ids` stays un-coerced — it carries date strings, not numbers.
    """
    h, l, c, v = map(_as_np, (high, low, close, volume))
    sid = list(session_ids)
    tp = (h + l + c) / 3.0
    out = np.full(c.shape, np.nan)
    cum_pv = 0.0
    cum_v = 0.0
    current = None
    for i in range(c.size):
        if sid[i] != current:
            current = sid[i]
            cum_pv = 0.0
            cum_v = 0.0
        if v[i] and v[i] > 0:
            cum_pv += tp[i] * v[i]
            cum_v += v[i]
            out[i] = cum_pv / cum_v
        elif cum_v > 0:
            out[i] = cum_pv / cum_v
    return out


def rsi(values, period: int = 14) -> np.ndarray:
    """Wilder's RSI."""
    arr = _as_np(values)
    out = np.full(arr.shape, np.nan)
    if arr.size <= period:
        return out
    delta = np.diff(arr)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()
    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period, delta.size):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
        if avg_loss == 0:
            out[i + 1] = 100.0
        else:
            out[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def macd(values, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(values, fast) - ema(values, slow)
    valid = ~np.isnan(line)
    sig = np.full(line.shape, np.nan)
    if valid.sum() > signal:
        sig[valid] = ema(line[valid], signal)
    hist = np.where(np.isnan(line) | np.isnan(sig), np.nan, line - sig)
    return line, sig, hist


def atr(high, low, close, period: int = 14) -> np.ndarray:
    """Wilder's ATR."""
    h, l, c = map(_as_np, (high, low, close))
    out = np.full(c.shape, np.nan)
    if c.size <= period:
        return out
    prev_c = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    out[period] = tr[1 : period + 1].mean()
    for i in range(period + 1, c.size):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def roc(values, period: int) -> np.ndarray:
    """Rate of change over `period` bars (fraction, e.g. 0.012 = +1.2%)."""
    arr = _as_np(values)
    out = np.full(arr.shape, np.nan)
    if arr.size > period:
        out[period:] = arr[period:] / arr[:-period] - 1.0
    return out


def rel_volume(volume, period: int = 20) -> np.ndarray:
    arr = _as_np(volume)
    avg = sma(arr, period)
    out = np.full(arr.shape, np.nan)
    mask = ~np.isnan(avg) & (avg > 0)
    out[mask] = arr[mask] / avg[mask]
    return out


def rolling_max(values, period: int) -> np.ndarray:
    """max of the `period` bars ENDING at i, excluding i itself (prior high)."""
    arr = _as_np(values)
    out = np.full(arr.shape, np.nan)
    for i in range(period, arr.size):
        out[i] = arr[i - period : i].max()
    return out


def rolling_min(values, period: int) -> np.ndarray:
    arr = _as_np(values)
    out = np.full(arr.shape, np.nan)
    for i in range(period, arr.size):
        out[i] = arr[i - period : i].min()
    return out


def swing_levels(high, low, left: int = 3, right: int = 3, max_levels: int = 4):
    """Recent swing highs (resistance) and swing lows (support) via fractal pivots.

    Returns (supports_desc, resistances_desc): lists of price levels, nearest first.
    Causal: a pivot at index i is only confirmed `right` bars later.
    """
    h, l = _as_np(high), _as_np(low)
    n = h.size
    highs: list[float] = []
    lows: list[float] = []
    for i in range(left, n - right):
        if h[i] == h[i - left : i + right + 1].max():
            highs.append(float(h[i]))
        if l[i] == l[i - left : i + right + 1].min():
            lows.append(float(l[i]))
    # de-dupe near-identical levels (0.05% band)
    def dedupe(vals: list[float]) -> list[float]:
        out: list[float] = []
        for v in reversed(vals):
            if not out or abs(v - out[-1]) / max(out[-1], 1e-9) > 0.0005:
                out.append(v)
        return out[:max_levels]

    return dedupe(lows), dedupe(highs)


IndicatorTimeframe = Literal["1m", "5m", "15m"]
