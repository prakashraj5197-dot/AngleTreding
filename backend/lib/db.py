"""Shared Mongo handle — import `client`/`db` from here (server.py, routers, seed.py)."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, IndexModel

load_dotenv(Path(__file__).parent.parent / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

logger = logging.getLogger(__name__)

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


async def ensure_indexes() -> None:
    for collection, models in INDEXES.items():
        for model in models:  # one at a time so a bad spec skips only itself
            try:
                await db[collection].create_indexes([model])
            except Exception as exc:  # never block boot on an index; the log line names what to fix
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)
