"""Database backend status — read-only, and never returns a credential.

The response tells the UI which store is active (mongo for the cloud preview,
sqlserver for the local/production AngleTrending database), whether the connection
works, and which optional migration procedures are present.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lib import repo_sql, sqlserver, store
from lib.auth import require_admin
from lib.db import db

router = APIRouter(prefix="/database", tags=["database"])


class DbStatusOut(BaseModel):
    backend: str
    label: str
    connected: bool
    configured: bool
    missing_env: list[str] = []
    host: str | None = None
    database: str | None = None
    driver_available: bool = False
    drivers: list[str] = []
    tables: int | None = None
    procedures: int | None = None
    server_utc: str | None = None
    detail: str = ""
    migration_001_applied: bool | None = None
    pending_migrations: list[str] = []
    store_tables_total: int | None = None
    store_tables_missing: list[str] = []


@router.get("/status", response_model=DbStatusOut)
async def status():
    state = await sqlserver.health()
    out = DbStatusOut(
        backend=state["backend"],
        label=("AngleTrending SQL Server" if state["backend"] == "sqlserver"
               else "MongoDB (cloud preview)"),
        connected=state["connected"],
        configured=state["configured"],
        missing_env=state["missing_env"],
        host=state["host"],
        database=state["database"],
        driver_available=state["driver_available"],
        drivers=state["drivers"],
        tables=state["tables"],
        procedures=state["procedures"],
        server_utc=state["server_utc"],
        detail=state["detail"],
    )
    if state["backend"] != "sqlserver":
        try:
            await db.command("ping")
            out.connected = True
        except Exception as exc:
            out.detail = f"MongoDB unreachable: {exc}"
        return out

    if state["connected"]:
        caps = await repo_sql.capabilities()
        out.migration_001_applied = bool(caps.get("usp_BacktestRuns_CreateV2"))
        if not out.migration_001_applied:
            out.pending_migrations = ["001_backtest_reporting_columns.sql"]
        # 002 creates the application store the whole app reads/writes through
        try:
            missing = await store.missing_tables()
        except Exception as exc:  # connection dropped between calls
            out.detail = f"{out.detail} Store check failed: {exc}"
            return out
        out.store_tables_total = len(store.COLUMNS)
        out.store_tables_missing = missing
        if missing:
            out.pending_migrations.append("002_app_store.sql")
            out.detail = (f"{out.detail} {len(missing)} application table(s) missing — run "
                          "migrations/002_app_store.sql.")
    return out


@router.get("/capabilities")
async def capabilities(admin: str = Depends(require_admin)):
    """Which migration-provided procedures exist (admin only)."""
    if not sqlserver.is_sqlserver():
        return {"backend": sqlserver.backend_name(), "capabilities": {}}
    return {"backend": "sqlserver", "capabilities": await repo_sql.capabilities()}
