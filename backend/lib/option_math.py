"""Option pricing math — vectorised Black-Scholes prices and greeks, plus IV utilities.

Used by the market-data simulator to synthesise option chains and by the backtester to
reprice historical contracts. All functions are deterministic.
"""

import numpy as np

RISK_FREE = 0.065  # documented assumption: flat 6.5% INR risk-free curve


def _d1_d2(spot, strike, t_years, vol, r=RISK_FREE):
    s, k, t, v = map(np.asarray, (spot, strike, t_years, vol))
    t = np.maximum(t, 1e-6)
    v = np.maximum(v, 1e-4)
    sqrt_t = np.sqrt(t)
    d1 = (np.log(s / k) + (r + 0.5 * v * v) * t) / (v * sqrt_t)
    d2 = d1 - v * sqrt_t
    return d1, d2


def _norm_cdf(x):
    from math import erf

    vec = np.vectorize(lambda z: 0.5 * (1.0 + erf(z / np.sqrt(2.0))))
    return vec(x)


def _norm_pdf(x):
    return np.exp(-0.5 * x * x) / np.sqrt(2.0 * np.pi)


def bs_price(spot, strike, t_years, vol, call: bool, r=RISK_FREE):
    d1, d2 = _d1_d2(spot, strike, t_years, vol, r)
    s, k = np.asarray(spot, dtype=float), np.asarray(strike, dtype=float)
    if call:
        return s * _norm_cdf(d1) - k * np.exp(-r * t_years) * _norm_cdf(d2)
    return k * np.exp(-r * t_years) * _norm_cdf(-d2) - s * _norm_cdf(-d1)


def bs_greeks(spot, strike, t_years, vol, call: bool, r=RISK_FREE):
    """Returns (delta, gamma, theta_per_day, vega_per_iv_point)."""
    s, k, t, v = map(np.asarray, (spot, strike, t_years, vol))
    t = np.maximum(t, 1e-6)
    d1, d2 = _d1_d2(s, k, t, v, r)
    gamma = _norm_pdf(d1) / (s * v * np.sqrt(t))
    vega = s * _norm_pdf(d1) * np.sqrt(t) / 100.0
    theta = (-(s * _norm_pdf(d1) * v) / (2 * np.sqrt(t)) - r * k * np.exp(-r * t) *
             (_norm_cdf(d2) if call else _norm_cdf(-d2))) / 365.0
    delta = _norm_cdf(d1) if call else -_norm_cdf(-d1)
    return float(delta), float(gamma), float(theta), float(vega)


def implied_vol(price, spot, strike, t_years, call: bool, r=RISK_FREE,
                lo: float = 0.01, hi: float = 3.0) -> float | None:
    """Bisection IV solver. Returns None when the price is outside arbitrage bounds."""
    price = float(price)
    s, k, t = float(spot), float(strike), max(float(t_years), 1e-6)
    intrinsic = max(0.0, (s - k) if call else (k - s))
    if price < intrinsic + 1e-6 or price > s:  # degenerate / violated bounds
        return None
    for _ in range(60):
        mid = (lo + hi) / 2.0
        p = float(bs_price(s, k, t, mid, call, r))
        if abs(p - price) < 1e-4:
            return mid
        if p > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def option_candles(spot_o, spot_h, spot_l, spot_c, strike, t_years, vol, call: bool):
    """Synthesise an option premium OHLC series from the underlying OHLC at fixed IV.

    Used by the backtester for SL/target monitoring at the best available historical
    resolution; the actual resolution is recorded with each backtest (spec 36.9).
    """
    o = float(bs_price(spot_o, strike, t_years, vol, call))
    h = float(bs_price(spot_h, strike, t_years, vol, call))
    l = float(bs_price(spot_l, strike, t_years, vol, call))
    c = float(bs_price(spot_c, strike, t_years, vol, call))
    return o, max(h, o, c), min(l, o, c), c
