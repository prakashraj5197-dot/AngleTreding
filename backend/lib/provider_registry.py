"""Provider registry — the single place that decides which market-data vendor is live.

Fail-safe contract (user's choice: "show the real state, never fake it"):
  • `settings.data.provider` selects the vendor. "simulated" is the demo feed; "angelone"
    is the real NSE/NFO feed via SmartAPI.
  • If the live vendor is selected but unconfigured or failing, `resolve()` still returns it
    and `health()` reports disconnected — callers then surface DATA STALE / MARKET CLOSED and
    the signal engine pauses. We never silently swap in simulated prices while claiming live.
  • Switching back to the simulator is an explicit admin action in Settings.
"""

from __future__ import annotations

import logging

from lib.broker_angelone import (
    AngelOneProvider,
    ProviderUnavailable,
    credentials_present,
    missing_credentials,
)
from lib.sim_provider import SimulatedProvider

logger = logging.getLogger("quantpulse.provider")

_simulated = SimulatedProvider()
_angelone: AngelOneProvider | None = None

PROVIDER_LABELS = {"simulated": "Built-in simulator", "angelone": "Angel One SmartAPI"}


def simulated() -> SimulatedProvider:
    return _simulated


def angelone() -> AngelOneProvider:
    global _angelone
    if _angelone is None:
        _angelone = AngelOneProvider()
    return _angelone


def resolve(provider_name: str | None):
    """Return the provider instance for the configured vendor name."""
    return angelone() if provider_name == "angelone" else _simulated


def health(provider_name: str | None) -> dict:
    """Connection state for /api/health, /api/provider/status and the UI badge."""
    name = provider_name if provider_name in PROVIDER_LABELS else "simulated"
    if name == "simulated":
        return {
            "provider": "simulated",
            "label": PROVIDER_LABELS["simulated"],
            "connected": True,
            "simulated": True,
            "configured": True,
            "missing_env": [],
            "last_login_ist": None,
            "last_error": None,
            "detail": "Deterministic simulated NSE feed (always-on demo session).",
        }

    p = angelone()
    configured = credentials_present()
    connected = False
    detail = ""
    if not configured:
        detail = (
            "Angel One is selected but credentials are missing: "
            + ", ".join(missing_credentials())
            + ". Add them to backend/.env and restart the backend."
        )
    else:
        try:
            p.load_instruments()
            p._connect()
            connected = True
            detail = "Angel One SmartAPI session active (NSE/NFO live feed)."
        except ProviderUnavailable as exc:
            connected = False
            detail = str(exc)
    return {
        "provider": "angelone",
        "label": PROVIDER_LABELS["angelone"],
        "connected": connected,
        "simulated": False,
        "configured": configured,
        "missing_env": missing_credentials(),
        "last_login_ist": p.last_login_ist,
        "last_error": p.last_error,
        "detail": detail,
    }
