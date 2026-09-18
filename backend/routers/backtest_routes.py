"""Backtesting routes — background jobs with Queued/Running/Completed/Failed status (AC-83)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from lib.backtest import run_backtest
from lib.db import db
from lib.dates import UTC, now_utc
from lib.sim_provider import INSTRUMENTS
from models.trading import BacktestJobOut, BacktestRunRequest, BacktestTradeOut

router = APIRouter(tags=["backtest"])


def _strip(d: dict) -> dict:
    d.pop("_id", None)
    return d


async def _runner(job_id: str) -> None:
    await db.backtest_jobs.update_one({"id": job_id}, {"$set": {
        "status": "RUNNING", "started_at": now_utc()}})
    try:
        await run_backtest(job_id)
    except Exception as exc:  # a failed job must report, never hang in RUNNING
        await db.backtest_jobs.update_one({"id": job_id}, {"$set": {
            "status": "FAILED", "error": f"{type(exc).__name__}: {exc}",
            "finished_at": now_utc()}})


@router.get("/backtest/dataset")
async def dataset_info():
    """Available stored history per symbol/timeframe, for the config form."""
    out = []
    for sym in INSTRUMENTS:
        for tf in ("1m", "5m", "15m"):
            first = await db.candles.find_one({"symbol": sym, "timeframe": tf}, sort=[("ts", 1)])
            last = await db.candles.find_one({"symbol": sym, "timeframe": tf}, sort=[("ts", -1)])
            if not first:
                continue
            count = await db.candles.count_documents({"symbol": sym, "timeframe": tf})
            out.append({"symbol": sym, "timeframe": tf, "candles": count,
                        "from": first["ts"], "to": last["ts"]})
    return {"datasets": out}


@router.post("/backtest/run", response_model=BacktestJobOut)
async def run(body: BacktestRunRequest):
    if body.symbol.upper() not in INSTRUMENTS:
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{body.symbol}'.")
    try:
        d0 = datetime.fromisoformat(body.from_date)
        d1 = datetime.fromisoformat(body.to_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Dates must be ISO format YYYY-MM-DD.")
    if d1 <= d0:
        raise HTTPException(status_code=422, detail="to_date must be after from_date.")
    if body.initial_capital <= 0:
        raise HTTPException(status_code=422, detail="initial_capital must be greater than zero.")
    if not (0 < body.risk_per_trade_pct <= 100):
        raise HTTPException(status_code=422, detail="risk_per_trade_pct must be between 0 and 100.")
    body.symbol = body.symbol.upper()
    job = {
        "id": str(uuid.uuid4()), "status": "QUEUED", "params": body.model_dump(),
        "created_at": now_utc(), "started_at": None, "finished_at": None,
        "progress": 0.0, "error": None, "warnings": [], "dataset_info": {},
        "metrics": None, "equity_curve": [], "trades_count": 0,
    }
    await db.backtest_jobs.insert_one(dict(job))
    asyncio.create_task(_runner(job["id"]))
    return BacktestJobOut(**_strip(job))


@router.get("/backtest/jobs", response_model=list[BacktestJobOut])
async def jobs(limit: int = 20):
    docs = await db.backtest_jobs.find().sort("created_at", -1).limit(min(limit, 50)).to_list(50)
    return [BacktestJobOut(**_strip(d)) for d in docs]


@router.get("/backtest/jobs/{job_id}", response_model=BacktestJobOut)
async def job(job_id: str):
    doc = await db.backtest_jobs.find_one({"id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Backtest job not found.")
    return BacktestJobOut(**_strip(doc))


@router.get("/backtest/jobs/{job_id}/trades", response_model=list[BacktestTradeOut])
async def job_trades(job_id: str, limit: int = 300, segment: str | None = None,
                     result: str | None = None):
    if not await db.backtest_jobs.find_one({"id": job_id}):
        raise HTTPException(status_code=404, detail="Backtest job not found.")
    q: dict = {"job_id": job_id}
    if segment:
        q["segment"] = segment
    if result:
        q["result"] = result.upper()
    docs = await db.backtest_trades.find(q).sort("n", 1).limit(min(limit, 1000)).to_list(1000)
    return [BacktestTradeOut(**_strip(d)) for d in docs]
