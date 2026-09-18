"""SQL Server connectivity for the AngleTrending database.

Design rules (user's constraints):
  * The application NEVER creates, drops, renames or alters a database object.
    Every read and write goes through the stored procedures that already exist.
  * Connection details live only in backend/.env and are read server-side.
    They are never returned by an API or shipped to the frontend.
  * The cloud preview cannot reach a LAN instance (PRAKASHPC\\SQLEXPRESS), so the
    backend is switchable: DB_BACKEND=mongo (preview/demo) | sqlserver (local/prod).

Connection string is assembled from discrete env vars so no secret is ever logged:
    SQLSERVER_HOST         PRAKASHPC\\SQLEXPRESS   (host, host\\instance or host,port)
    SQLSERVER_DATABASE     AngleTrending
    SQLSERVER_TRUSTED      1 to use Windows auth, 0/absent for SQL auth
    SQLSERVER_USER         sa                     (ignored when SQLSERVER_TRUSTED=1)
    SQLSERVER_PASSWORD     ******                 (ignored when SQLSERVER_TRUSTED=1)
    SQLSERVER_DRIVER       ODBC Driver 18 for SQL Server
    SQLSERVER_ENCRYPT      yes|no                 (default no for a LAN instance)
    SQLSERVER_TRUST_CERT   yes|no                 (default yes for a self-signed cert)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Sequence

logger = logging.getLogger("quantpulse.sqlserver")

DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"


class SqlServerUnavailable(RuntimeError):
    """Raised when the AngleTrending database cannot be reached or a proc call fails."""


def backend_name() -> str:
    """'sqlserver' or 'mongo' — chosen by DB_BACKEND, defaulting to mongo."""
    return (os.environ.get("DB_BACKEND") or "mongo").strip().lower()


def is_sqlserver() -> bool:
    return backend_name() == "sqlserver"


def config() -> dict[str, str]:
    return {
        "host": (os.environ.get("SQLSERVER_HOST") or "").strip(),
        "database": (os.environ.get("SQLSERVER_DATABASE") or "AngleTrending").strip(),
        "user": (os.environ.get("SQLSERVER_USER") or "").strip(),
        "password": os.environ.get("SQLSERVER_PASSWORD") or "",
        "driver": (os.environ.get("SQLSERVER_DRIVER") or DEFAULT_DRIVER).strip(),
        "trusted": (os.environ.get("SQLSERVER_TRUSTED") or "0").strip(),
        "encrypt": (os.environ.get("SQLSERVER_ENCRYPT") or "no").strip(),
        "trust_cert": (os.environ.get("SQLSERVER_TRUST_CERT") or "yes").strip(),
    }


def missing_config() -> list[str]:
    c = config()
    missing: list[str] = []
    if not c["host"]:
        missing.append("SQLSERVER_HOST")
    if not c["database"]:
        missing.append("SQLSERVER_DATABASE")
    if c["trusted"] not in ("1", "true", "yes"):
        if not c["user"]:
            missing.append("SQLSERVER_USER")
        if not c["password"]:
            missing.append("SQLSERVER_PASSWORD")
    return missing


def connection_string(redacted: bool = False) -> str:
    """Build the ODBC connection string. `redacted=True` is safe to log."""
    c = config()
    parts = [
        f"DRIVER={{{c['driver']}}}",
        f"SERVER={c['host']}",
        f"DATABASE={c['database']}",
        f"Encrypt={c['encrypt']}",
        f"TrustServerCertificate={c['trust_cert']}",
        "Connection Timeout=8",
    ]
    if c["trusted"] in ("1", "true", "yes"):
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={c['user']}")
        parts.append("PWD=***" if redacted else f"PWD={c['password']}")
    return ";".join(parts) + ";"


# --------------------------------------------------------------------------- #
# connection handling
# --------------------------------------------------------------------------- #
# pyodbc is synchronous, so every call is executed on a worker thread and the
# connection is created per call. SQL Server's own ODBC connection pooling keeps
# this cheap, and it avoids holding a socket open across an idle 5-minute cycle.

_import_error: str | None = None
try:  # pyodbc needs a system ODBC driver, which a LAN/prod host will have
    import pyodbc  # type: ignore
except Exception as exc:  # pragma: no cover - only on hosts without unixODBC
    pyodbc = None  # type: ignore
    _import_error = str(exc)


def driver_available() -> bool:
    if pyodbc is None:
        return False
    try:
        return any("SQL Server" in d for d in pyodbc.drivers())
    except Exception:
        return False


def installed_drivers() -> list[str]:
    if pyodbc is None:
        return []
    try:
        return list(pyodbc.drivers())
    except Exception:
        return []


def _connect_sync():
    if pyodbc is None:
        raise SqlServerUnavailable(
            f"pyodbc is not importable on this host ({_import_error}). "
            "Install unixODBC + msodbcsql18 (Linux) or run the backend on Windows.")
    missing = missing_config()
    if missing:
        raise SqlServerUnavailable(
            "SQL Server connection is not configured. Set " + ", ".join(missing) +
            " in backend/.env.")
    if not driver_available():
        raise SqlServerUnavailable(
            "No SQL Server ODBC driver is installed. Install 'ODBC Driver 18 for SQL Server' "
            f"(drivers found: {installed_drivers() or 'none'}).")
    try:
        return pyodbc.connect(connection_string(), autocommit=True)
    except Exception as exc:
        raise SqlServerUnavailable(f"cannot connect to {config()['host']} — {exc}") from exc


def _rows_to_dicts(cursor) -> list[dict[str, Any]]:
    if cursor.description is None:
        return []
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _exec_sync(sql: str, params: Sequence[Any], fetch: bool) -> list[dict[str, Any]]:
    conn = _connect_sync()
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql, tuple(params))
            if not fetch:
                return []
            out = _rows_to_dicts(cur)
            # a proc may return several result sets; walk to the first non-empty one
            while not out and cur.nextset():
                out = _rows_to_dicts(cur)
            return out
        finally:
            cur.close()
    except SqlServerUnavailable:
        raise
    except Exception as exc:
        raise SqlServerUnavailable(f"{sql.split(' ')[1] if ' ' in sql else sql}: {exc}") from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# public async API — stored procedures only
# --------------------------------------------------------------------------- #

async def call_proc(name: str, /, **params: Any) -> list[dict[str, Any]]:
    """EXEC a stored procedure with named parameters and return its rows.

    Parameters are passed as ODBC placeholders (never string-formatted), so values
    cannot alter the statement. Only the procedure NAME is interpolated, and every
    call site in this codebase passes a hard-coded literal.
    """
    if not name.replace("_", "").replace(".", "").isalnum():
        raise SqlServerUnavailable(f"refusing to execute suspicious procedure name {name!r}")
    keys = list(params.keys())
    placeholders = ", ".join(f"@{k} = ?" for k in keys)
    sql = f"EXEC {name} {placeholders}" if keys else f"EXEC {name}"
    values = [params[k] for k in keys]
    return await asyncio.to_thread(_exec_sync, sql, values, True)


async def call_proc_noresult(name: str, /, **params: Any) -> None:
    await call_proc(name, **params)


async def scalar(name: str, column: str, /, **params: Any) -> Any:
    rows = await call_proc(name, **params)
    return rows[0].get(column) if rows else None


async def ping() -> dict[str, Any]:
    """Health probe: verifies connectivity and that the expected objects exist.

    Reads only metadata views — it changes nothing.
    """
    sql = """
        SELECT
            (SELECT COUNT(*) FROM sys.tables WHERE schema_id = SCHEMA_ID('dbo')) AS TableCount,
            (SELECT COUNT(*) FROM sys.procedures WHERE schema_id = SCHEMA_ID('dbo')) AS ProcCount,
            DB_NAME() AS DatabaseName,
            CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(50)) AS ProductVersion,
            SYSUTCDATETIME() AS ServerUtc
    """
    rows = await asyncio.to_thread(_exec_sync, sql, [], True)
    return rows[0] if rows else {}


async def health() -> dict[str, Any]:
    """Never raises — always returns a state the UI can render."""
    state: dict[str, Any] = {
        "backend": backend_name(),
        "configured": not missing_config(),
        "missing_env": missing_config(),
        "driver_available": driver_available(),
        "drivers": installed_drivers(),
        "host": config()["host"] or None,
        "database": config()["database"],
        "connected": False,
        "detail": "",
        "tables": None,
        "procedures": None,
        "server_utc": None,
    }
    if not is_sqlserver():
        state["detail"] = "DB_BACKEND=mongo — SQL Server is not in use by this instance."
        return state
    try:
        info = await ping()
        state["connected"] = True
        state["tables"] = info.get("TableCount")
        state["procedures"] = info.get("ProcCount")
        state["server_utc"] = str(info.get("ServerUtc"))
        state["detail"] = (f"Connected to {info.get('DatabaseName')} "
                           f"(SQL Server {info.get('ProductVersion')}).")
    except SqlServerUnavailable as exc:
        state["detail"] = str(exc)
    return state


async def select(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """Run a read-only statement (metadata inventory / health only).

    Application data access goes through `call_proc`; this exists so the verifier can
    inventory sys.tables and sys.procedures without adding a procedure to your database.
    """
    lowered = sql.strip().lower()
    if not lowered.startswith("select"):
        raise SqlServerUnavailable("select() accepts SELECT statements only")
    return await asyncio.to_thread(_exec_sync, sql, list(params), True)
