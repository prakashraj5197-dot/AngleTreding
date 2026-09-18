"""QuantPulse F&O Signal & Backtesting Engine — FastAPI entry point.

Every route is registered on `api_router` (prefix /api); `app.include_router(api_router)`
is the last statement. Two background workers run under the lifespan:
  • signal evaluation loop (default 60s; the strategy's own cooldown/duplicate gates make
    the effective new-signal cadence match §36.12/36.13)
  • lifecycle monitor (5s) for entry fills, SL/target/expiry tracking and paper positions
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
from lib.broker_angelone import ProviderUnavailable  # noqa: E402
from lib.db import client, db, ensure_indexes  # noqa: E402
from lib.dates import now_utc  # noqa: E402
from routers import (  # noqa: E402
    backtest_routes,
    market,
    paper,
    provider as provider_router,
    scanner,
    settings_routes,
    signals as signals_router,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("quantpulse")


async def _evaluation_loop() -> None:
    """Periodic strategy evaluation for every analysed underlying (AC-01/81)."""
    from lib.signal_engine import ANALYSIS_SYMBOLS, evaluate_symbol, get_settings

    await asyncio.sleep(4)
    while True:
        try:
            s = await get_settings()
            for sym in ANALYSIS_SYMBOLS:
                try:
                    st = await evaluate_symbol(sym, s)
                    logger.info("eval %s → %s score=%s %s", sym, st.direction,
                                st.display_score, st.no_trade_reason or "")
                except Exception as exc:
                    logger.exception("evaluation failed for %s: %s", sym, exc)
            await asyncio.sleep(max(15, s.strategy.eval_interval_sec))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("evaluation loop error: %s", exc)
            await asyncio.sleep(15)


async def _monitor_loop() -> None:
    """Tick-level SL/target/entry monitoring + paper position tracking (§36.12)."""
    from lib.signal_engine import monitor_once

    await asyncio.sleep(8)
    while True:
        try:
            await monitor_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("monitor loop error: %s", exc)
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.index_task = asyncio.create_task(ensure_indexes())
    app.state.eval_task = asyncio.create_task(_evaluation_loop())
    app.state.monitor_task = asyncio.create_task(_monitor_loop())
    yield
    for name in ("eval_task", "monitor_task"):
        task = getattr(app.state, name, None)
        if task:
            task.cancel()
    client.close()


app = FastAPI(title="QuantPulse F&O Signal Engine", lifespan=lifespan)

api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {
        "service": "QuantPulse F&O Signal & Backtesting Engine",
        "version": "1.0.0",
        "disclaimer": "Probability-based signal generator and paper-trading simulation. "
                      "Not investment advice. No real orders are ever placed.",
        "server_time_utc": now_utc(),
    }


api_router.include_router(market.router)
api_router.include_router(signals_router.router)
api_router.include_router(scanner.router)
api_router.include_router(backtest_routes.router)
api_router.include_router(paper.router)
api_router.include_router(settings_routes.router)
api_router.include_router(provider_router.router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(ProviderUnavailable)
async def provider_unavailable_handler(request: Request, exc: ProviderUnavailable):
    """AC-74: surface the real feed state instead of pretending data exists."""
    logger.error("provider unavailable on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": f"Market-data provider unavailable: {exc}"},
    )


# Include the router in the main app — must stay the last statement.
app.include_router(api_router)
