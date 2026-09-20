"""SQL Server document store — the real data layer when DB_BACKEND=sqlserver.

Why this shape
--------------
The whole application (engine, risk, backtest, paper trading, settings, auth) talks to
one handle exposed by `lib.db.db`. This module implements the exact subset of that
handle's API against SQL Server, so flipping DB_BACKEND in backend/.env moves 100% of
the application's reads and writes to the AngleTrending database with no other change.

Storage model
-------------
One additive table per collection (dbo.Fno*), created by
`migrations/002_app_store.sql` — nothing here issues DDL and no pre-existing object is
ever touched. Each row keeps:

  * `Doc`  NVARCHAR(MAX)  — the complete document as JSON (source of truth, so nothing
                            is lost and datetimes round-trip with their timezone)
  * typed, indexed columns for every field the application filters or sorts on, derived
    from `Doc` on write (see COLUMNS below)

Supported query surface (everything the codebase actually uses):
  filters   : equality, $in, $nin, $gte, $gt, $lte, $lt, $ne
  updates   : $set (read-merge-write, so nested keys behave like Mongo)
  methods   : find/find_one/count_documents/insert_one/insert_many/update_one/
              update_many/replace_one/delete_one/delete_many/bulk_write/drop
An unsupported operator raises instead of silently returning wrong rows.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Iterable, Sequence

from lib import sqlserver

logger = logging.getLogger("quantpulse.store")

# --------------------------------------------------------------------------- #
# schema: collection -> {field: sql column type}
# migrations/002_app_store.sql is GENERATED from this map (gen_store_schema.py),
# so the table definitions and this adapter can never drift apart.
# --------------------------------------------------------------------------- #
STR = "NVARCHAR(128)"
STR_LONG = "NVARCHAR(400)"
DT = "DATETIME2(3)"
FLT = "FLOAT"
INT = "INT"
BIT = "BIT"

COLUMNS: dict[str, dict[str, str]] = {
    "settings": {},
    "paper_account": {},
    "candles": {"symbol": STR, "timeframe": STR, "ts": DT},
    "signals": {
        "id": STR, "status": STR, "symbol": STR, "day_ist": STR, "strategy_name": STR_LONG,
        "strategy_version": STR, "result": STR, "option_type": STR, "direction": STR,
        "score": FLT, "created_at": DT, "exit_time": DT, "paper_executed": BIT,
    },
    "engine_state": {"symbol": STR},
    "sim_state": {"symbol": STR},
    "option_chain_snapshots": {"underlying": STR, "expiry": STR, "ts": DT},
    "notifications": {"signal_id": STR, "type": STR, "read": BIT, "ts": DT},
    "paper_positions": {
        "id": STR, "signal_id": STR, "symbol": STR, "status": STR,
        "entry_time": DT, "exit_time": DT,
    },
    "backtest_jobs": {"id": STR, "symbol": STR, "status": STR, "created_at": DT},
    "backtest_trades": {"job_id": STR, "n": INT, "segment": STR, "result": STR},
    "sessions": {"token": STR_LONG, "email": STR_LONG, "expires_at": DT},
}

# unique constraints (also the natural upsert keys) — used by the generated DDL
UNIQUE: dict[str, list[str]] = {
    "candles": ["symbol", "timeframe", "ts"],
    "signals": ["id"],
    "engine_state": ["symbol"],
    "sim_state": ["symbol"],
    "paper_positions": ["id"],
    "backtest_jobs": ["id"],
    "sessions": ["token"],
}

# secondary indexes for the hot sort/filter paths
INDEXES: dict[str, list[list[str]]] = {
    "candles": [["symbol", "timeframe", "ts"]],
    "signals": [["created_at"], ["status", "created_at"], ["day_ist", "symbol"],
                ["symbol", "strategy_name", "status"]],
    "notifications": [["ts"], ["read", "ts"]],
    "paper_positions": [["status", "entry_time"], ["status", "exit_time"], ["signal_id"]],
    "backtest_jobs": [["created_at"]],
    "backtest_trades": [["job_id", "n"]],
    "option_chain_snapshots": [["underlying", "ts"]],
    "sessions": [["expires_at"]],
}

TABLE_PREFIX = "Fno"


def table_name(collection: str) -> str:
    """dbo.FnoBacktestTrades for 'backtest_trades' — additive, never an existing object."""
    camel = "".join(p.capitalize() for p in collection.split("_"))
    return f"dbo.{TABLE_PREFIX}{camel}"


# --------------------------------------------------------------------------- #
# JSON round-trip (datetimes keep their timezone, unlike BSON)
# --------------------------------------------------------------------------- #

def _default(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"__dt__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    return str(value)


def _hook(obj: dict[str, Any]) -> Any:
    if len(obj) == 1:
        if "__dt__" in obj:
            return datetime.fromisoformat(obj["__dt__"])
        if "__date__" in obj:
            return date.fromisoformat(obj["__date__"])
    return obj


def dumps(doc: dict[str, Any]) -> str:
    return json.dumps(doc, default=_default)


def loads(raw: str) -> dict[str, Any]:
    return json.loads(raw, object_hook=_hook)


def _bind(value: Any) -> Any:
    """Convert a Python value into something pyodbc can bind to a typed column."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None)  # DATETIME2 holds naive UTC
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float, str)) or value is None:
        return value
    return json.dumps(value, default=_default)


class _Result:
    """Stand-in for pymongo's result objects (only the attributes we read)."""

    def __init__(self, matched: int = 0, modified: int = 0, deleted: int = 0,
                 upserted_id: Any = None, inserted_id: Any = None,
                 inserted_ids: list[Any] | None = None) -> None:
        self.matched_count = matched
        self.modified_count = modified
        self.deleted_count = deleted
        self.upserted_id = upserted_id
        self.inserted_id = inserted_id
        self.inserted_ids = inserted_ids or []
        self.acknowledged = True


class StoreError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# query translation
# --------------------------------------------------------------------------- #
_OPS = {"$gte": ">=", "$gt": ">", "$lte": "<=", "$lt": "<", "$ne": "<>"}


class SqlCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.columns = COLUMNS.get(name, {})
        self.table = table_name(name)

    # --- field/expression mapping ----------------------------------------- #
    def _expr(self, field: str) -> str:
        if field == "_id":
            return "DocId"
        if field in self.columns:
            return f"[{field}]"
        # not indexed: read it straight out of the JSON document
        return f"JSON_VALUE(Doc, '$.{field}')"

    def _where(self, flt: dict[str, Any] | None) -> tuple[str, list[Any]]:
        if not flt:
            return "", []
        clauses: list[str] = []
        params: list[Any] = []
        for field, cond in flt.items():
            col = self._expr(field)
            if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
                for op, val in cond.items():
                    if op == "$in":
                        vals = list(val)
                        if not vals:
                            clauses.append("1 = 0")
                            continue
                        clauses.append(f"{col} IN ({', '.join('?' * len(vals))})")
                        params.extend(_bind(v) for v in vals)
                    elif op == "$nin":
                        vals = list(val)
                        if vals:
                            clauses.append(
                                f"({col} IS NULL OR {col} NOT IN ({', '.join('?' * len(vals))}))")
                            params.extend(_bind(v) for v in vals)
                    elif op in _OPS:
                        clauses.append(f"{col} {_OPS[op]} ?")
                        params.append(_bind(val))
                    elif op == "$exists":
                        clauses.append(f"{col} IS {'NOT ' if val else ''}NULL")
                    else:
                        raise StoreError(
                            f"operator {op!r} is not supported by the SQL Server store "
                            f"(collection {self.name})")
            elif cond is None:
                clauses.append(f"{col} IS NULL")
            else:
                clauses.append(f"{col} = ?")
                params.append(_bind(cond))
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    def _order(self, sort: Any) -> str:
        if not sort:
            return ""
        pairs: Sequence[tuple[str, int]]
        if isinstance(sort, str):
            pairs = [(sort, 1)]
        elif isinstance(sort, tuple):
            pairs = [sort]  # type: ignore[list-item]
        else:
            pairs = list(sort)
        parts = [f"{self._expr(f)} {'ASC' if int(d) >= 0 else 'DESC'}" for f, d in pairs]
        return "ORDER BY " + ", ".join(parts)

    def _row_values(self, doc: dict[str, Any]) -> tuple[list[str], list[Any]]:
        """(column names, bound values) for one document — DocId + typed cols + Doc."""
        cols = ["DocId"] + [f"[{c}]" for c in self.columns] + ["Doc"]
        vals: list[Any] = [
            None if doc.get("_id") is None else str(doc.get("_id"))
        ]
        for field in self.columns:
            vals.append(_bind(doc.get(field)))
        vals.append(dumps({k: v for k, v in doc.items() if k != "_id"}))
        return cols, vals

    # --- reads ------------------------------------------------------------- #
    def _select(self, flt: dict[str, Any] | None, sort: Any = None,
                limit: int | None = None) -> tuple[str, list[Any]]:
        where, params = self._where(flt)
        top = f"TOP ({int(limit)}) " if limit else ""
        sql = f"SELECT {top}DocId, Doc FROM {self.table} {where} {self._order(sort)}".strip()
        return sql, params

    def _decode(self, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in rows:
            doc = loads(r["Doc"]) if r.get("Doc") else {}
            if r.get("DocId") is not None:
                doc["_id"] = r["DocId"]
            out.append(doc)
        return out

    async def find_one(self, flt: dict[str, Any] | None = None, projection: Any = None,
                       sort: Any = None, **_: Any) -> dict[str, Any] | None:
        sql, params = self._select(flt, sort, 1)
        rows = await sqlserver.select(sql, params)
        docs = self._decode(rows)
        return docs[0] if docs else None

    def find(self, flt: dict[str, Any] | None = None, projection: Any = None,
             sort: Any = None, limit: int | None = None, **_: Any) -> "SqlCursor":
        return SqlCursor(self, flt, sort, limit)

    async def count_documents(self, flt: dict[str, Any] | None = None, **_: Any) -> int:
        where, params = self._where(flt)
        rows = await sqlserver.select(f"SELECT COUNT(*) AS n FROM {self.table} {where}", params)
        return int(rows[0]["n"]) if rows else 0

    async def distinct(self, field: str, flt: dict[str, Any] | None = None) -> list[Any]:
        where, params = self._where(flt)
        col = self._expr(field)
        rows = await sqlserver.select(
            f"SELECT DISTINCT {col} AS v FROM {self.table} {where}", params)
        return [r["v"] for r in rows if r["v"] is not None]

    # --- writes ------------------------------------------------------------ #
    async def insert_one(self, doc: dict[str, Any], **_: Any) -> _Result:
        cols, vals = self._row_values(doc)
        sql = (f"INSERT INTO {self.table} ({', '.join(cols)}) "
               f"VALUES ({', '.join('?' * len(vals))})")
        await sqlserver.execute(sql, vals)
        return _Result(inserted_id=doc.get("_id") or doc.get("id"))

    async def insert_many(self, docs: Sequence[dict[str, Any]], ordered: bool = True,
                          **_: Any) -> _Result:
        docs = list(docs)
        if not docs:
            return _Result()
        cols, _first = self._row_values(docs[0])
        rows = [self._row_values(d)[1] for d in docs]
        sql = (f"INSERT INTO {self.table} ({', '.join(cols)}) "
               f"VALUES ({', '.join('?' * len(cols))})")
        await sqlserver.execute_many(sql, rows)
        return _Result(inserted_ids=[d.get("_id") or d.get("id") for d in docs])

    async def replace_one(self, flt: dict[str, Any], doc: dict[str, Any],
                          upsert: bool = False, **_: Any) -> _Result:
        merged = dict(doc)
        # a filter on _id / a natural key must survive the replace, as it does in Mongo
        for field, cond in (flt or {}).items():
            if not isinstance(cond, dict) and field not in merged:
                merged[field] = cond
        cols, vals = self._row_values(merged)
        where, wparams = self._where(flt)
        assignments = ", ".join(f"{c} = ?" for c in cols)
        updated = await sqlserver.execute(
            f"UPDATE {self.table} SET {assignments} {where}", vals + wparams)
        if updated == 0 and upsert:
            return await self.insert_one(merged)
        return _Result(matched=updated, modified=updated)

    async def update_one(self, flt: dict[str, Any], update: dict[str, Any],
                         upsert: bool = False, **_: Any) -> _Result:
        setter = self._setter(update)
        existing = await self.find_one(flt)
        if existing is None:
            if not upsert:
                return _Result()
            seed = {f: c for f, c in (flt or {}).items() if not isinstance(c, dict)}
            seed.update(setter)
            res = await self.insert_one(seed)
            return _Result(upserted_id=res.inserted_id)
        merged = dict(existing)
        merged.update(setter)
        return await self._write_doc(merged, flt)

    async def update_many(self, flt: dict[str, Any], update: dict[str, Any],
                          **_: Any) -> _Result:
        setter = self._setter(update)
        docs = await self.find(flt).to_list(100000)
        for doc in docs:
            merged = dict(doc)
            merged.update(setter)
            await self._write_doc(merged, {"_rowkey": doc})
        return _Result(matched=len(docs), modified=len(docs))

    async def delete_one(self, flt: dict[str, Any], **_: Any) -> _Result:
        where, params = self._where(flt)
        n = await sqlserver.execute(
            f"DELETE FROM {self.table} WHERE RowId IN "
            f"(SELECT TOP (1) RowId FROM {self.table} {where})", params)
        return _Result(deleted=n)

    async def delete_many(self, flt: dict[str, Any] | None = None, **_: Any) -> _Result:
        where, params = self._where(flt)
        n = await sqlserver.execute(f"DELETE FROM {self.table} {where}", params)
        return _Result(deleted=n)

    async def drop(self) -> None:
        """Empties the table. It never drops the object itself (no DDL from the app)."""
        await sqlserver.execute(f"DELETE FROM {self.table}", [])

    async def bulk_write(self, ops: Sequence[Any], ordered: bool = True, **_: Any) -> _Result:
        """Batched upsert for pymongo UpdateOne/ReplaceOne ops (seeding candles).

        Every op must be a whole-document upsert keyed on equality fields, which is what
        the seeders build. Batches go through a staging table + MERGE so a 250k-candle
        seed stays a handful of round-trips instead of a quarter-million.
        """
        rows: list[list[Any]] = []
        keys: list[str] | None = None
        for op in ops:
            flt = getattr(op, "_filter", None)
            doc = getattr(op, "_doc", None)
            if flt is None or doc is None:
                raise StoreError("bulk_write supports UpdateOne/ReplaceOne with upsert only")
            payload = doc.get("$set", doc) if isinstance(doc, dict) else doc
            merged = dict(payload)
            for field, cond in flt.items():
                if not isinstance(cond, dict) and field not in merged:
                    merged[field] = cond
            op_keys = [k for k in flt if not isinstance(flt[k], dict)]
            if keys is None:
                keys = op_keys
            rows.append(self._row_values(merged)[1])
        if not rows:
            return _Result()
        cols, _ = self._row_values({})
        merge_keys = keys or UNIQUE.get(self.name) or []
        await sqlserver.merge_batch(self.table, cols, rows, merge_keys)
        return _Result(matched=len(rows), modified=len(rows))

    # --- helpers ----------------------------------------------------------- #
    @staticmethod
    def _setter(update: dict[str, Any]) -> dict[str, Any]:
        if "$set" in update:
            unsupported = [k for k in update if k.startswith("$") and k != "$set"]
            if unsupported:
                raise StoreError(f"update operators {unsupported} are not supported")
            return dict(update["$set"])
        if any(k.startswith("$") for k in update):
            raise StoreError(f"unsupported update document {list(update)}")
        return dict(update)

    async def _write_doc(self, doc: dict[str, Any], flt: dict[str, Any]) -> _Result:
        """Rewrite one row identified either by a query filter or by its natural key."""
        cols, vals = self._row_values(doc)
        assignments = ", ".join(f"{c} = ?" for c in cols)
        key_filter: dict[str, Any]
        if "_rowkey" in flt:  # update_many path: re-identify by natural key
            src = flt["_rowkey"]
            natural = UNIQUE.get(self.name) or (["_id"] if src.get("_id") is not None else [])
            key_filter = {k: src.get(k) for k in natural} or {
                k: src.get(k) for k in list(self.columns)[:3]}
        else:
            key_filter = flt
        where, wparams = self._where(key_filter)
        n = await sqlserver.execute(
            f"UPDATE {self.table} SET {assignments} {where}", vals + wparams)
        return _Result(matched=n, modified=n)


class SqlCursor:
    """Mirrors the motor cursor chain used in this codebase: .sort().limit().to_list()."""

    def __init__(self, coll: SqlCollection, flt: dict[str, Any] | None,
                 sort: Any = None, limit: int | None = None) -> None:
        self._coll = coll
        self._filter = flt
        self._sort = sort
        self._limit = limit

    def sort(self, key_or_list: Any, direction: int | None = None) -> "SqlCursor":
        self._sort = [(key_or_list, direction if direction is not None else 1)] \
            if isinstance(key_or_list, str) else key_or_list
        return self

    def limit(self, n: int) -> "SqlCursor":
        self._limit = n
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        cap = min(x for x in (self._limit, length) if x) if (self._limit or length) else None
        sql, params = self._coll._select(self._filter, self._sort, cap)
        return self._coll._decode(await sqlserver.select(sql, params))

    def __aiter__(self) -> "SqlCursor":
        self._buffer: list[dict[str, Any]] | None = None
        self._pos = 0
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._buffer is None:
            self._buffer = await self.to_list(self._limit or 100000)
        if self._pos >= len(self._buffer):
            raise StopAsyncIteration
        doc = self._buffer[self._pos]
        self._pos += 1
        return doc


class SqlStore:
    """Stands in for the motor database handle: db.signals, db["candles"], db.command()."""

    def __init__(self) -> None:
        self._cache: dict[str, SqlCollection] = {}

    def __getitem__(self, name: str) -> SqlCollection:
        if name not in self._cache:
            if name not in COLUMNS:
                raise StoreError(
                    f"collection {name!r} has no SQL Server table. Add it to "
                    "lib/store.py COLUMNS and regenerate migrations/002_app_store.sql.")
            self._cache[name] = SqlCollection(name)
        return self._cache[name]

    def __getattr__(self, name: str) -> SqlCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    async def command(self, _cmd: Any = None, **__: Any) -> dict[str, Any]:
        await sqlserver.ping()
        return {"ok": 1}


class SqlClientShim:
    """server.py calls client.close() on shutdown; connections here are per-call."""

    def close(self) -> None:
        return None


async def missing_tables() -> list[str]:
    """Which Fno* tables migration 002 still has to create (used by /api/database/status)."""
    rows = await sqlserver.select(
        "SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID('dbo') AND name LIKE ?",
        [f"{TABLE_PREFIX}%"])
    present = {r["name"].lower() for r in rows}
    return [table_name(c).split(".")[-1] for c in COLUMNS
            if table_name(c).split(".")[-1].lower() not in present]
