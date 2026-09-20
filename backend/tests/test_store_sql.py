"""SQL translation tests for the SQL Server document store (lib/store.py).

These run without a database: `lib.sqlserver`'s executors are replaced with recorders,
so the tests assert the exact T-SQL and bound parameters the adapter produces for the
query shapes the application actually issues. That is where a wrong translation would
silently return wrong rows once DB_BACKEND=sqlserver.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "app")

from lib import sqlserver, store  # noqa: E402


class Recorder:
    def __init__(self) -> None:
        self.selects: list[tuple[str, list]] = []
        self.executes: list[tuple[str, list]] = []
        self.merges: list[tuple[str, list[str], list, list[str]]] = []
        self.rows: list[dict] = []
        self.affected = 1

    async def select(self, sql, params=()):
        self.selects.append((" ".join(sql.split()), list(params)))
        return self.rows

    async def execute(self, sql, params=()):
        self.executes.append((" ".join(sql.split()), list(params)))
        return self.affected

    async def execute_many(self, sql, rows):
        self.executes.append((" ".join(sql.split()), list(rows)))
        return len(rows)

    async def merge_batch(self, table, cols, rows, keys):
        self.merges.append((table, list(cols), list(rows), list(keys)))
        return len(rows)


@pytest.fixture()
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(sqlserver, "select", r.select)
    monkeypatch.setattr(sqlserver, "execute", r.execute)
    monkeypatch.setattr(sqlserver, "execute_many", r.execute_many)
    monkeypatch.setattr(sqlserver, "merge_batch", r.merge_batch)
    return r


def col(collection: str) -> store.SqlCollection:
    return store.SqlCollection(collection)


# --------------------------------------------------------------------------- #
# schema wiring
# --------------------------------------------------------------------------- #

def test_table_names_are_additive_and_namespaced():
    assert store.table_name("backtest_trades") == "dbo.FnoBacktestTrades"
    assert store.table_name("signals") == "dbo.FnoSignals"
    # nothing collides with the user's existing AngleTrending objects
    for c in store.COLUMNS:
        assert store.table_name(c).startswith("dbo.Fno")


def test_every_collection_the_app_uses_has_a_table():
    used = {"settings", "candles", "signals", "engine_state", "sim_state",
            "option_chain_snapshots", "notifications", "paper_positions",
            "paper_account", "backtest_jobs", "backtest_trades", "sessions"}
    assert used <= set(store.COLUMNS)


def test_unknown_collection_fails_loudly():
    with pytest.raises(store.StoreError):
        store.SqlStore()["not_a_collection"]


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_find_one_by_indexed_field(rec):
    await col("signals").find_one({"id": "abc"})
    sql, params = rec.selects[-1]
    assert sql == "SELECT TOP (1) DocId, Doc FROM dbo.FnoSignals WHERE [id] = ?"
    assert params == ["abc"]


@pytest.mark.asyncio
async def test_find_one_by_mongo_id_maps_to_docid(rec):
    await col("settings").find_one({"_id": "app"})
    sql, params = rec.selects[-1]
    assert "WHERE DocId = ?" in sql and params == ["app"]


@pytest.mark.asyncio
async def test_in_and_sort_and_limit(rec):
    await col("signals").find({"status": {"$in": ["ACTIVE", "TARGET1_HIT"]}}) \
        .sort("created_at", -1).limit(50).to_list(500)
    sql, params = rec.selects[-1]
    assert sql == ("SELECT TOP (50) DocId, Doc FROM dbo.FnoSignals "
                   "WHERE [status] IN (?, ?) ORDER BY [created_at] DESC")
    assert params == ["ACTIVE", "TARGET1_HIT"]


@pytest.mark.asyncio
async def test_nin_tolerates_null(rec):
    await col("signals").count_documents(
        {"day_ist": "2026-01-02", "status": {"$nin": ["CANCELLED", "DATA_ERROR"]}})
    sql, params = rec.selects[-1]
    assert sql == ("SELECT COUNT(*) AS n FROM dbo.FnoSignals WHERE [day_ist] = ? AND "
                   "([status] IS NULL OR [status] NOT IN (?, ?))")
    assert params == ["2026-01-02", "CANCELLED", "DATA_ERROR"]


@pytest.mark.asyncio
async def test_range_operators_and_datetime_binding(rec):
    t = datetime(2026, 1, 2, 3, 30, tzinfo=timezone.utc)
    await col("candles").find({"symbol": "NIFTY", "timeframe": "5m",
                               "ts": {"$gte": t, "$lte": t}}).to_list(10)
    sql, params = rec.selects[-1]
    assert "[ts] >= ? AND [ts] <= ?" in sql
    # aware datetimes are normalised to naive UTC for DATETIME2 columns
    assert params[2] == datetime(2026, 1, 2, 3, 30) and params[2].tzinfo is None


@pytest.mark.asyncio
async def test_unindexed_field_falls_back_to_json_value(rec):
    await col("signals").find_one({"expiry": "2026-01-29"})
    sql, _ = rec.selects[-1]
    assert "JSON_VALUE(Doc, '$.expiry') = ?" in sql


@pytest.mark.asyncio
async def test_empty_filter_selects_all(rec):
    await col("backtest_jobs").find().sort("created_at", -1).limit(5).to_list(50)
    sql, params = rec.selects[-1]
    assert sql == ("SELECT TOP (5) DocId, Doc FROM dbo.FnoBacktestJobs "
                   "ORDER BY [created_at] DESC")
    assert params == []


@pytest.mark.asyncio
async def test_unsupported_operator_raises_instead_of_guessing(rec):
    with pytest.raises(store.StoreError):
        await col("signals").find_one({"score": {"$regex": "x"}})


@pytest.mark.asyncio
async def test_documents_and_datetimes_round_trip(rec):
    t = datetime(2026, 1, 2, 9, 20, tzinfo=timezone.utc)
    doc = {"id": "s1", "created_at": t, "factors": [{"name": "Trend", "score": 20}],
           "nested": {"deep": {"ok": True}}, "pnl_points": -12.5}
    rec.rows = [{"DocId": None, "Doc": store.dumps(doc)}]
    got = await col("signals").find_one({"id": "s1"})
    assert got["created_at"] == t and got["created_at"].tzinfo is not None
    assert got["factors"][0]["score"] == 20
    assert got["nested"]["deep"]["ok"] is True
    assert got["pnl_points"] == -12.5


@pytest.mark.asyncio
async def test_async_iteration_matches_motor(rec):
    rec.rows = [{"DocId": None, "Doc": store.dumps({"id": f"p{i}"})} for i in range(3)]
    seen = [d["id"] async for d in col("paper_positions").find({"status": "OPEN"})]
    assert seen == ["p0", "p1", "p2"]


# --------------------------------------------------------------------------- #
# writes
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_insert_one_fills_typed_columns_and_doc(rec):
    t = datetime(2026, 1, 2, 9, 20, tzinfo=timezone.utc)
    await col("signals").insert_one({"id": "s1", "status": "ACTIVE", "symbol": "NIFTY",
                                     "score": 82.0, "created_at": t, "reason": "breakout"})
    sql, params = rec.executes[-1]
    assert sql.startswith("INSERT INTO dbo.FnoSignals (DocId, [id], [status]")
    assert "ACTIVE" in params and 82.0 in params
    doc_json = params[-1]
    assert '"reason": "breakout"' in doc_json and "__dt__" in doc_json


@pytest.mark.asyncio
async def test_update_one_merges_like_mongo_set(rec):
    rec.rows = [{"DocId": None, "Doc": store.dumps(
        {"id": "s1", "status": "ACTIVE", "score": 82.0, "reason": "keep me"})}]
    await col("signals").update_one({"id": "s1"}, {"$set": {"status": "TARGET1_HIT"}})
    sql, params = rec.executes[-1]
    assert sql.startswith("UPDATE dbo.FnoSignals SET")
    assert sql.endswith("WHERE [id] = ?")
    assert "TARGET1_HIT" in params           # new value written to the typed column
    assert any("keep me" in str(p) for p in params)  # untouched fields preserved


@pytest.mark.asyncio
async def test_update_one_without_match_is_a_noop(rec):
    rec.rows = []
    res = await col("signals").update_one({"id": "nope"}, {"$set": {"status": "X"}})
    assert res.modified_count == 0 and not rec.executes


@pytest.mark.asyncio
async def test_update_one_upsert_seeds_from_filter(rec):
    rec.rows = []
    await col("paper_account").update_one({"_id": "main"}, {"$set": {"capital": 11000}},
                                          upsert=True)
    sql, params = rec.executes[-1]
    assert sql.startswith("INSERT INTO dbo.FnoPaperAccount")
    assert params[0] == "main" and '"capital": 11000' in params[-1]


@pytest.mark.asyncio
async def test_replace_one_upsert_inserts_when_absent(rec):
    rec.affected = 0
    await col("engine_state").replace_one({"symbol": "NIFTY"}, {"direction": "BULLISH"},
                                          upsert=True)
    assert rec.executes[0][0].startswith("UPDATE dbo.FnoEngineState SET")
    assert rec.executes[1][0].startswith("INSERT INTO dbo.FnoEngineState")
    # the filter key survives the replace, as it does in Mongo
    assert "NIFTY" in rec.executes[1][1]


@pytest.mark.asyncio
async def test_update_many_rewrites_each_match(rec):
    rec.rows = [{"DocId": None, "Doc": store.dumps({"id": "s1", "paper_executed": True})},
                {"DocId": None, "Doc": store.dumps({"id": "s2", "paper_executed": True})}]
    res = await col("signals").update_many({"paper_executed": True},
                                           {"$set": {"paper_executed": False}})
    assert res.modified_count == 2
    assert len(rec.executes) == 2
    assert all(e[0].endswith("WHERE [id] = ?") for e in rec.executes)


@pytest.mark.asyncio
async def test_delete_one_limits_to_a_single_row(rec):
    await col("sessions").delete_one({"token": "tok"})
    sql, params = rec.executes[-1]
    assert sql == ("DELETE FROM dbo.FnoSessions WHERE RowId IN (SELECT TOP (1) RowId "
                   "FROM dbo.FnoSessions WHERE [token] = ?)")
    assert params == ["tok"]


@pytest.mark.asyncio
async def test_delete_many_and_drop_never_emit_ddl(rec):
    await col("paper_positions").delete_many({})
    await col("candles").drop()
    for sql, _ in rec.executes:
        assert sql.startswith("DELETE FROM")
        sqlserver.guard_no_ddl(sql)  # must not raise


@pytest.mark.asyncio
async def test_bulk_write_upserts_on_the_filter_key(rec):
    from pymongo import UpdateOne

    t = datetime(2026, 1, 2, 9, 20, tzinfo=timezone.utc)
    row = {"symbol": "NIFTY", "timeframe": "5m", "ts": t, "open": 1.0, "close": 2.0}
    await col("candles").bulk_write([UpdateOne(
        {"symbol": "NIFTY", "timeframe": "5m", "ts": t}, {"$set": row}, upsert=True)])
    table, cols, rows, keys = rec.merges[-1]
    assert table == "dbo.FnoCandles"
    assert keys == ["symbol", "timeframe", "ts"]
    assert cols == ["DocId", "[symbol]", "[timeframe]", "[ts]", "Doc"]
    assert rows[0][1] == "NIFTY" and '"close": 2.0' in rows[0][-1]


# --------------------------------------------------------------------------- #
# safety
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("sql", [
    "DROP TABLE dbo.Signals", "ALTER TABLE dbo.Signals ADD x INT",
    "TRUNCATE TABLE dbo.Signals", "CREATE TABLE x (a INT)",
])
def test_ddl_is_refused(sql):
    with pytest.raises(sqlserver.SqlServerUnavailable):
        sqlserver.guard_no_ddl(sql)


def test_generated_migration_matches_the_adapter_schema():
    """migrations/002_app_store.sql must declare every table/column the adapter writes."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "migrations", "002_app_store.sql")
    ddl = open(path, encoding="utf-8").read()
    for collection, columns in store.COLUMNS.items():
        assert f"CREATE TABLE {store.table_name(collection)}" in ddl
        for field in columns:
            assert f"[{field}]" in ddl
    assert "ALTER TABLE" not in ddl.upper()
    assert "DROP TABLE" not in ddl.upper().replace("DROP TABLE #STAGE", "")
