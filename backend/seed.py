"""Idempotent seed: historical candles (1m/5m/15m), default settings, paper account.

Run: cd /app/backend && python seed.py [--days 520] [--reset]

Generates ~2 years of deterministic NSE-style history for NIFTY and BANKNIFTY from the
simulated provider (spec 36.6: minimum 2 years of underlying history for backtesting).
Historical option contracts are synthesised on demand at each historical timestamp by the
same provider (36.7/36.8: ±10 strikes around ATM, both CE and PE, multiple expiries),
which keeps the dataset reproducible without storing tens of millions of option rows.
"""

import argparse
import asyncio
import sys

from pymongo import UpdateOne

from lib.db import db, ensure_indexes
from lib.dates import n_trading_days_back, now_utc
from lib.sim_provider import INSTRUMENTS, SimulatedProvider
from models.trading import AppSettings

SEED_SYMBOLS = ["NIFTY", "BANKNIFTY"]


async def seed_candles(symbol: str, days: int) -> int:
    provider = SimulatedProvider()
    day_keys = n_trading_days_back(days)
    start = INSTRUMENTS[symbol].base_price * 0.72  # drift up into today's level over the window
    total = 0
    batch: list[UpdateOne] = []
    for tf, rows in provider.generate_history(symbol, day_keys, start):
        for r in rows:
            batch.append(UpdateOne(
                {"symbol": r["symbol"], "timeframe": r["timeframe"], "ts": r["ts"]},
                {"$set": r}, upsert=True))
        if len(batch) >= 5000:
            await db.candles.bulk_write(batch, ordered=False)
            total += len(batch)
            batch = []
            print(f"  {symbol}: {total:,} candles written", flush=True)
    if batch:
        await db.candles.bulk_write(batch, ordered=False)
        total += len(batch)
    return total


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=520, help="trading days of history per symbol (~2 years)")
    ap.add_argument("--reset", action="store_true", help="drop existing candles/signals first")
    args = ap.parse_args()

    if args.reset:
        for coll in ("candles", "signals", "engine_state", "sim_state", "notifications",
                     "paper_positions", "paper_account", "backtest_jobs", "backtest_trades",
                     "option_chain_snapshots"):
            await db[coll].drop()
        print("dropped existing collections")

    await ensure_indexes()

    if not await db.settings.find_one({"_id": "app"}):
        defaults = AppSettings()
        defaults.updated_at = now_utc()
        await db.settings.replace_one({"_id": "app"}, defaults.model_dump(), upsert=True)
        print(f"settings seeded (strategy {defaults.strategy.name} v{defaults.strategy.version})")
    else:
        print("settings already present — left untouched")

    if not await db.paper_account.find_one({"_id": "main"}):
        s = AppSettings()
        await db.paper_account.insert_one({
            "_id": "main", "id": "main", "start_capital": s.paper.start_capital,
            "cash": s.paper.start_capital, "realized_pnl": 0.0,
            "peak_equity": s.paper.start_capital,
            "created_at": now_utc(), "updated_at": now_utc()})
        print(f"paper account seeded with ₹{s.paper.start_capital:,.0f} virtual capital")

    for symbol in SEED_SYMBOLS:
        have = await db.candles.count_documents({"symbol": symbol, "timeframe": "5m"})
        if have >= args.days * 70:
            print(f"{symbol}: {have:,} 5m candles already stored — skipping")
            continue
        print(f"{symbol}: generating {args.days} trading days of 1m/5m/15m history…", flush=True)
        total = await seed_candles(symbol, args.days)
        print(f"{symbol}: {total:,} candle upserts done")

    for symbol in SEED_SYMBOLS:
        for tf in ("1m", "5m", "15m"):
            count = await db.candles.count_documents({"symbol": symbol, "timeframe": tf})
            first = await db.candles.find_one({"symbol": symbol, "timeframe": tf}, sort=[("ts", 1)])
            last = await db.candles.find_one({"symbol": symbol, "timeframe": tf}, sort=[("ts", -1)])
            if first:
                print(f"  {symbol} {tf}: {count:,} candles  {first['ts'].date()} → {last['ts'].date()}")
    print("seed complete")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
