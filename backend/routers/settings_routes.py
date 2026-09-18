"""Settings + auth routes. Configuration changes require an authenticated admin (AC-76/77)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from lib.auth import (
    ADMIN_EMAIL,
    SESSION_COOKIE,
    create_session,
    current_admin,
    destroy_session,
    require_admin,
    verify_credentials,
)
from lib.db import db
from lib.signal_engine import get_settings, save_settings
from models.trading import AppSettings, LoginRequest, TokenOut

router = APIRouter(tags=["settings"])


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginRequest, response: Response):
    if not verify_credentials(body.email, body.password):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = await create_session(body.email.strip().lower())
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=12 * 3600, path="/")
    return TokenOut(ok=True, email=body.email.strip().lower())


@router.post("/auth/logout", response_model=TokenOut)
async def logout(response: Response, admin: str | None = Depends(current_admin)):
    from fastapi import Cookie  # noqa: F401

    response.delete_cookie(SESSION_COOKIE, path="/")
    return TokenOut(ok=True, email=None)


@router.get("/auth/me", response_model=TokenOut)
async def me(admin: str | None = Depends(current_admin)):
    return TokenOut(ok=admin is not None, email=admin)


@router.get("/settings", response_model=AppSettings)
async def read_settings():
    """Readable without auth (the UI shows thresholds); mutations require admin."""
    return await get_settings(force=True)


def _validate(new: AppSettings) -> list[str]:
    errs: list[str] = []
    s, o, r = new.strategy, new.option_selection, new.risk
    if not (0 < s.min_signal_score <= 100):
        errs.append("Minimum signal score must be between 1 and 100.")
    if s.min_risk_reward < 0.1:
        errs.append("Minimum risk/reward must be at least 0.1.")
    if s.ema_fast >= s.ema_slow:
        errs.append("EMA fast period must be smaller than EMA slow period.")
    if s.rsi_period < 2 or s.rsi_period > 100:
        errs.append("RSI period must be between 2 and 100.")
    if s.atr_period < 2 or s.atr_period > 100:
        errs.append("ATR period must be between 2 and 100.")
    if s.volume_multiplier <= 0:
        errs.append("Volume multiplier must be greater than zero.")
    if s.t1_rr <= 0 or s.t2_rr <= s.t1_rr:
        errs.append("Target 2 R-multiple must be greater than Target 1.")
    if not (0 < s.sl_pct_of_premium < 100):
        errs.append("Stop-loss percentage of premium must be between 0 and 100.")
    if s.cooldown_min < 0 or s.signal_validity_min <= 0:
        errs.append("Cooldown cannot be negative and signal validity must be positive.")
    if o.min_oi < 0 or o.min_volume < 0:
        errs.append("Minimum OI and volume cannot be negative.")
    if o.max_spread_pct <= 0:
        errs.append("Maximum bid/ask spread must be greater than zero.")
    if o.atm_range < 1 or o.atm_range > 20:
        errs.append("ATM strike range must be between 1 and 20.")
    if r.capital <= 0:
        errs.append("Capital must be greater than zero.")
    if r.max_risk_per_trade <= 0:
        errs.append("Maximum risk per trade must be greater than zero.")
    if r.max_risk_per_trade > r.capital:
        errs.append("Maximum risk per trade cannot exceed total capital.")
    if r.daily_loss_limit <= 0:
        errs.append("Daily loss limit must be greater than zero.")
    if r.consecutive_loss_limit < 1:
        errs.append("Consecutive loss limit must be at least 1.")
    if r.max_trades_per_day < 1:
        errs.append("Maximum trades per day must be at least 1.")
    if new.data.price_fresh_s < 1 or new.data.chain_fresh_s < 1:
        errs.append("Freshness thresholds must be at least 1 second.")
    if new.paper.start_capital <= 0:
        errs.append("Paper start capital must be greater than zero.")
    return errs


@router.put("/settings", response_model=AppSettings)
async def update_settings(body: AppSettings, admin: str = Depends(require_admin)):
    errors = _validate(body)
    if errors:
        raise HTTPException(status_code=422, detail=" ".join(errors))
    current = await get_settings(force=True)
    # strategy versioning: any parameter change creates a new version (§22, 36.40)
    if body.strategy.model_dump(exclude={"version"}) != current.strategy.model_dump(exclude={"version"}):
        major, minor, patch = (current.strategy.version.split(".") + ["0", "0"])[:3]
        body.strategy.version = f"{major}.{int(minor) + 1}.0"
    return await save_settings(body)


@router.post("/settings/reset", response_model=AppSettings)
async def reset_settings(admin: str = Depends(require_admin)):
    fresh = AppSettings()
    return await save_settings(fresh)
