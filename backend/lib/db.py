"""Shared data handle — import `client`/`db` from here (server.py, routers, seed.py).

ONE SWITCH: `DB_BACKEND` in backend/.env decides where every read and write goes.

    DB_BACKEND=sqlserver   → AngleTrending SQL Server (lib/store.py; tables from
                             migrations/002_app_store.sql). Use this locally/in prod.
    DB_BACKEND=mongo       → MongoDB (default; the cloud preview cannot reach a LAN
                             SQL Server instance, so the demo keeps working)

Both handles expose the same API, so no router, engine or script needs to know which
store is live.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, IndexModel

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

BACKEND = (os.environ.get("DB_BACKEND") or "mongo").strip().lower()

# One entry per collection: every field a route filters, sorts, or dedupes on.
INDEXES: dict[str, list[IndexModel]] = {
    "candles": [
        # dedupe key: one candle per (symbol, timeframe, ts) — duplicate ticks/bars upsert (AC-03)
        IndexModel([("symbol", ASCENDING), ("timeframe", ASCENDING), ("ts", ASCENDING)],
                   name="symbol_tf_ts", unique=True),
        IndexModel([("symbol", ASCENDING), ("timeframe", ASCENDING), ("ts", DESCENDING)],
                   name="symbol_tf_ts_desc"),
    ],
    "signals": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("created_at", DESCENDING)], name="created_desc"),
        IndexModel([("status", ASCENDING), ("created_at", DESCENDING)], name="status_created"),
        IndexModel([("symbol", ASCENDING), ("day_ist", ASCENDING)], name="symbol_day"),
        IndexModel([("day_ist", ASCENDING), ("symbol", ASCENDING), ("strategy_name", ASCENDING),
                    ("result", ASCENDING)], name="day_symbol_strategy_result"),
    ],
    "engine_state": [IndexModel([("symbol", ASCENDING)], name="symbol", unique=True)],
    "sim_state": [IndexModel([("symbol", ASCENDING)], name="symbol", unique=True)],
    "option_chain_snapshots": [
        IndexModel([("underlying", ASCENDING), ("ts", DESCENDING)], name="underlying_ts"),
    ],
    "notifications": [
        IndexModel([("ts", DESCENDING)], name="ts_desc"),
        IndexModel([("read", ASCENDING), ("ts", DESCENDING)], name="read_ts"),
        IndexModel([("signal_id", ASCENDING), ("type", ASCENDING)], name="signal_type"),
    ],
    "paper_positions": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("status", ASCENDING), ("entry_time", DESCENDING)], name="status_entry"),
        IndexModel([("signal_id", ASCENDING), ("status", ASCENDING)], name="signal_status"),
        IndexModel([("status", ASCENDING), ("exit_time", DESCENDING)], name="status_exit"),
    ],
    "backtest_jobs": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("created_at", DESCENDING)], name="created_desc"),
    ],
    "backtest_trades": [
        IndexModel([("job_id", ASCENDING), ("n", ASCENDING)], name="job_n"),
        IndexModel([("job_id", ASCENDING), ("segment", ASCENDING)], name="job_segment"),
    ],
    "sessions": [
        IndexModel([("token", ASCENDING)], name="token", unique=True),
        IndexModel([("expires_at", ASCENDING)], name="expires_ttl", expireAfterSeconds=0),
    ],
}


if BACKEND == "sqlserver":
    from lib.store import SqlClientShim, SqlStore

    client = SqlClientShim()   # type: ignore[assignment]
    db = SqlStore()            # type: ignore[assignment]
    logger.info("data backend = SQL Server (AngleTrending)")
else:
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])  # type: ignore[assignment]
    db = client[os.environ["DB_NAME"]]                    # type: ignore[assignment]
    logger.info("data backend = MongoDB (%s)", os.environ.get("DB_NAME"))


async def ensure_indexes() -> None:
    """Mongo: create the indexes above. SQL Server: nothing — the indexes ship with
    migrations/002_app_store.sql, and the application never issues DDL."""
    if BACKEND == "sqlserver":
        from lib import store
        try:
            missing = await store.missing_tables()
        except Exception as exc:
            logger.error("SQL Server store unreachable: %s", exc)
            return
        if missing:
            logger.error("SQL Server store is missing %d table(s): %s — run "
                         "migrations/002_app_store.sql against your AngleTrending database.",
                         len(missing), ", ".join(missing))
        else:
            logger.info("SQL Server store ready — all %d application tables present.",
                        len(store.COLUMNS))
        return
    for collection, models in INDEXES.items():
        for model in models:  # one at a time so a bad spec skips only itself
            try:
                await db[collection].create_indexes([model])
            except Exception as exc:  # never block boot on an index; the log line names what to fix
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)
