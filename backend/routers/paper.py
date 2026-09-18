"""Paper trading routes (§16, AC-56..59) — virtual positions only, never a real order."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from lib.db import db
from lib.dates import now_utc
from lib.signal_engine import (
    close_paper,
    execute_paper,
    get_settings,
    paper_account_view,
)
from models.trading import PaperAccount, PaperPosition

router = APIRouter(tags=["paper"])


def _strip(d: dict) -> dict:
    d.pop("_id", None)
    return d


@router.get("/paper/account", response_model=PaperAccount)
async def account():
    return PaperAccount(**await paper_account_view())


@router.get("/paper/positions", response_model=list[PaperPosition])
async def positions(status: str | None = None, limit: int = 100):
    q = {"status": status.upper()} if status else {}
    docs = await db.paper_positions.find(q).sort("entry_time", -1).limit(min(limit, 300)).to_list(300)
    out = []
    for d in docs:
        d = _strip(d)
        if d["status"] == "OPEN":
            d["unrealized"] = round((d["last_price"] - d["entry_price"]) * d["qty"], 2)
        out.append(PaperPosition(**d))
    return out


@router.post("/paper/execute/{signal_id}", response_model=PaperPosition)
async def execute(signal_id: str):
    """Open a virtual position from an ACTIVE signal. NO real broker order is placed."""
    s = await get_settings()
    acct = await paper_account_view()
    if acct.get("risk_blocked_reason"):
        raise HTTPException(status_code=409, detail=acct["risk_blocked_reason"])
    ok, msg, pos = await execute_paper(signal_id)
    if not ok or pos is None:
        raise HTTPException(status_code=409, detail=msg)
    pos = _strip(dict(pos))
    pos["unrealized"] = 0.0
    return PaperPosition(**pos)


@router.post("/paper/close/{position_id}")
async def close(position_id: str):
    ok, msg = await close_paper(position_id, "MANUAL_EXIT")
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    return {"ok": True, "message": msg}


@router.post("/paper/reset")
async def reset():
    s = await get_settings()
    await db.paper_positions.delete_many({})
    await db.paper_account.replace_one({"_id": "main"}, {
        "_id": "main", "id": "main", "start_capital": s.paper.start_capital,
        "cash": s.paper.start_capital, "realized_pnl": 0.0,
        "peak_equity": s.paper.start_capital,
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }, upsert=True)
    await db.signals.update_many({"paper_executed": True}, {"$set": {"paper_executed": False}})
    return {"ok": True, "message": f"Paper account reset to ₹{s.paper.start_capital:,.0f}."}
