"""Market-data provider routes — status, admin connection test, instrument refresh.

Broker credentials are read from backend/.env inside the adapter and are NEVER returned
here; the client code is masked and only presence/absence of each variable is reported
(AC-75).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from lib import provider_registry
from lib.auth import require_admin
from lib.broker_angelone import ProviderUnavailable
from lib.signal_engine import (
    ANALYSIS_SYMBOLS,
    evaluate_symbol,
    get_provider,
    get_settings,
    save_settings,
)
from models.trading import ProviderStatusOut, ProviderTestOut

logger = logging.getLogger("quantpulse.provider")

router = APIRouter(prefix="/provider", tags=["provider"])


@router.get("/status", response_model=ProviderStatusOut)
async def provider_status():
    s = await get_settings()
    return ProviderStatusOut(**provider_registry.health(s.data.provider))


@router.post("/test", response_model=ProviderTestOut)
async def provider_test(admin: str = Depends(require_admin)):
    """Attempt a real Angel One login + instrument-master load and report the outcome."""
    p = provider_registry.angelone()
    result = p.login_check()
    return ProviderTestOut(
        ok=bool(result.get("ok")),
        message=str(result.get("message") or ""),
        client_code_masked=result.get("client_code_masked"),
        last_login_ist=result.get("last_login_ist"),
        missing_env=list(result.get("missing_env") or []),
        option_contracts=result.get("option_contracts") or {},
    )


@router.post("/instruments/refresh", response_model=ProviderTestOut)
async def refresh_instruments(admin: str = Depends(require_admin)):
    """Force a re-download of the daily OpenAPIScripMaster instrument dump."""
    p = provider_registry.angelone()
    try:
        p.load_instruments(force=True)
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ProviderTestOut(
        ok=True,
        message="Instrument master refreshed.",
        option_contracts={k: len(v) for k, v in p._options.items()},
    )


@router.post("/select/{name}", response_model=ProviderStatusOut)
async def select_provider(name: str, admin: str = Depends(require_admin)):
    """Switch the live data vendor. Kept an explicit admin action — never automatic."""
    if name not in provider_registry.PROVIDER_LABELS:
        raise HTTPException(status_code=422, detail=f"Unknown provider '{name}'.")
    s = await get_settings()
    s.data.provider = name  # type: ignore[assignment]
    if name == "angelone":
        # a real exchange feed has real trading hours; the always-on demo clock would lie
        s.data.session_mode = "market_hours"
        s.data.force_stale = False
    else:
        # the simulator is the demo/backtest feed — keep its continuous session so the
        # dashboard stays alive outside NSE hours
        s.data.session_mode = "always_on"
    await save_settings(s)
    await get_settings(force=True)
    get_provider()
    # re-evaluate straight away so the dashboard's direction card reflects the NEW feed
    # instead of holding the previous provider's reason until the next 60s cycle
    for sym in ANALYSIS_SYMBOLS:
        try:
            await evaluate_symbol(sym)
        except Exception as exc:  # a dead feed is expected here — the state row records it
            logger.warning("post-switch evaluation for %s: %s", sym, exc)
    return ProviderStatusOut(**provider_registry.health(name))
