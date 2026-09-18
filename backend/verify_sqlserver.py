"""Verify the AngleTrending SQL Server integration end to end.

Run this ON YOUR MACHINE (where PRAKASHPC\\SQLEXPRESS is reachable):

    cd backend
    python verify_sqlserver.py            # read-only checks
    python verify_sqlserver.py --write    # also exercises the write procedures

Read-only mode touches nothing: it connects, inventories the tables/procedures the
application depends on, and reports which optional (migration 001) procedures exist.
--write additionally inserts a clearly marked probe row through each write procedure
(instrument 'ZZTEST-VERIFY', a signal on underlying 'ZZTEST', a paper trade, a backtest
run) so you can confirm the full path works. It never drops or alters an object, and it
prints the exact ids it created so you can delete them if you wish.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
os.environ["DB_BACKEND"] = "sqlserver"  # this tool always targets SQL Server

from lib import repo_sql as repo  # noqa: E402
from lib import sqlserver as S  # noqa: E402

OK = "  [ OK ]"
BAD = "  [FAIL]"
SKIP = "  [SKIP]"

REQUIRED_TABLES = [
    "Instruments", "MarketTicks", "MarketCandles", "OptionChainSnapshots",
    "Strategies", "StrategyParameters", "Signals", "SignalHistory",
    "PaperTrades", "PaperTradeTransactions", "BacktestRuns", "BacktestTrades",
    "AppSettings", "FeedHealthLogs", "ApplicationLogs",
]

REQUIRED_PROCS = [
    "usp_Instruments_GetActive", "usp_Instruments_GetBySymbolToken", "usp_Instruments_Upsert",
    "usp_MarketTicks_Insert", "usp_MarketTicks_GetLatest",
    "usp_MarketCandles_Upsert", "usp_MarketCandles_Get",
    "usp_OptionChain_SaveSnapshot", "usp_OptionChain_GetLatest",
    "usp_Strategies_GetActive", "usp_Strategies_SaveParameter", "usp_Strategies_GetParameters",
    "usp_Signals_Create", "usp_Signals_GetLatest", "usp_Signals_GetHistory",
    "usp_Signals_UpdateResult",
    "usp_PaperTrades_Create", "usp_PaperTrades_Close", "usp_PaperTrades_GetOpen",
    "usp_PaperTrades_GetHistory", "usp_PaperTrades_GetPnLSummary",
    "usp_BacktestRuns_Create", "usp_BacktestTrades_Insert", "usp_BacktestRuns_Complete",
    "usp_BacktestRuns_GetResults",
    "usp_AppSettings_Get", "usp_AppSettings_Upsert",
    "usp_FeedHealth_Save", "usp_ApplicationLogs_Write", "usp_ApplicationLogs_Get",
]

MIGRATION_PROCS = [
    "usp_BacktestRuns_CreateV2", "usp_BacktestRuns_CompleteV2", "usp_BacktestRuns_SetStatus",
    "usp_BacktestRuns_GetList", "usp_BacktestTrades_InsertV2", "usp_BacktestTrades_GetByRun",
]

failures: list[str] = []


def report(label: str, ok: bool, detail: str = "") -> None:
    print(f"{OK if ok else BAD} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


async def check_connection() -> bool:
    print("\n=== 1. Connection ===")
    print(f"  connection string: {S.connection_string(redacted=True)}")
    missing = S.missing_config()
    if missing:
        report("configuration", False, "missing env: " + ", ".join(missing))
        return False
    report("configuration", True, f"host={S.config()['host']} db={S.config()['database']}")
    if not S.driver_available():
        report("ODBC driver", False,
               f"install 'ODBC Driver 18 for SQL Server' (found: {S.installed_drivers() or 'none'})")
        return False
    report("ODBC driver", True, ", ".join(S.installed_drivers()))
    try:
        info = await S.ping()
    except S.SqlServerUnavailable as exc:
        report("connect", False, str(exc))
        return False
    report("connect", True, f"{info.get('DatabaseName')} / SQL Server {info.get('ProductVersion')}"
                            f" / server UTC {info.get('ServerUtc')}")
    return True


async def check_objects() -> None:
    print("\n=== 2. Schema inventory (read-only) ===")
    rows = await S.select(
        "SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID('dbo')")
    tables = {r["name"] for r in rows}
    for t in REQUIRED_TABLES:
        report(f"table dbo.{t}", t in tables)
    rows = await S.select(
        "SELECT name FROM sys.procedures WHERE schema_id = SCHEMA_ID('dbo')")
    procs = {r["name"] for r in rows}
    for p in REQUIRED_PROCS:
        report(f"proc dbo.{p}", p in procs)

    print("\n=== 3. Optional procedures from migrations/001 ===")
    missing_mig = [p for p in MIGRATION_PROCS if p not in procs]
    for p in MIGRATION_PROCS:
        present = p in procs
        print(f"{OK if present else SKIP} dbo.{p}" + ("" if present else " — not yet created"))
    if missing_mig:
        print("\n  -> Run migrations/001_backtest_reporting_columns.sql to enable full")
        print("     backtest persistence (gross/net P&L, costs, profit factor, R multiple,")
        print("     dataset segment, market regime). The app works without it, but those")
        print("     figures are computed for display only and not stored.")


async def check_reads() -> None:
    print("\n=== 4. Read procedures ===")
    probes = [
        ("usp_Instruments_GetActive", repo.instruments_active()),
        ("usp_Strategies_GetActive", repo.strategies_active()),
        ("usp_AppSettings_Get", repo.app_settings_get()),
        ("usp_PaperTrades_GetOpen", repo.paper_open()),
        ("usp_ApplicationLogs_Get", repo.logs_get(top=5)),
        ("usp_Signals_GetLatest", repo.signals_latest(top=5)),
    ]
    for name, coro in probes:
        try:
            res = await coro
            n = len(res) if hasattr(res, "__len__") else 1
            report(name, True, f"{n} row(s)")
        except S.SqlServerUnavailable as exc:
            report(name, False, str(exc))

    now = datetime.now(UTC)
    try:
        res = await repo.signals_history(from_time=now - timedelta(days=30), to_time=now)
        report("usp_Signals_GetHistory", True, f"{len(res)} row(s) in last 30 days")
    except S.SqlServerUnavailable as exc:
        report("usp_Signals_GetHistory", False, str(exc))
    try:
        res = await repo.paper_pnl_summary(from_time=now - timedelta(days=30), to_time=now)
        report("usp_PaperTrades_GetPnLSummary", True, str(res)[:100])
    except S.SqlServerUnavailable as exc:
        report("usp_PaperTrades_GetPnLSummary", False, str(exc))


async def check_writes() -> None:
    """Exercises every write procedure with clearly-marked probe data."""
    print("\n=== 5. Write procedures (probe rows, prefixed ZZTEST) ===")
    now = datetime.now(UTC).replace(tzinfo=None)  # SQL DATETIME2 columns are naive UTC
    today = date.today()

    instrument_id = None
    try:
        instrument_id = await repo.instrument_upsert(
            exchange="NFO", segment="NFO", trading_symbol="ZZTEST-VERIFY",
            symbol_token="999999", underlying="ZZTEST", instrument_type="OPTIDX",
            expiry=today + timedelta(days=7), strike=25000, option_type="CE",
            lot_size=65, tick_size=0.05, is_active=False)
        report("usp_Instruments_Upsert", instrument_id is not None,
               f"InstrumentId={instrument_id}")
    except S.SqlServerUnavailable as exc:
        report("usp_Instruments_Upsert", False, str(exc))

    if instrument_id:
        for label, coro in [
            ("usp_MarketTicks_Insert", repo.tick_insert(
                instrument_id=instrument_id, ts=now, ltp=123.45, open_=120, high=126,
                low=119, close=123.45, volume=1000, oi=50000, bid=123.4, ask=123.5,
                source="VERIFY")),
            ("usp_MarketCandles_Upsert", repo.candle_upsert(
                instrument_id=instrument_id, timeframe="5m",
                start=now.replace(second=0, microsecond=0), o=120, h=126, l=119, c=123.45,
                volume=1000, oi=50000)),
            ("usp_OptionChain_SaveSnapshot", repo.option_chain_save_row(
                instrument_id=instrument_id, underlying="ZZTEST", snapshot_time=now,
                expiry=today + timedelta(days=7), strike=25000, option_type="CE",
                spot=25010, ltp=123.45, volume=1000, oi=50000, change_in_oi=1200,
                iv=0.142, delta=0.51, gamma=0.0004, theta=-8.2, vega=6.1,
                bid=123.4, bid_qty=75, ask=123.5, ask_qty=75, source="VERIFY")),
        ]:
            try:
                await coro
                report(label, True)
            except S.SqlServerUnavailable as exc:
                report(label, False, str(exc))

        # idempotency: the same candle twice must not duplicate (AC-03)
        try:
            await repo.candle_upsert(
                instrument_id=instrument_id, timeframe="5m",
                start=now.replace(second=0, microsecond=0), o=120, h=127, l=119, c=124,
                volume=1100, oi=50500)
            rows = await repo.candles_get(
                instrument_id=instrument_id, timeframe="5m",
                from_time=now - timedelta(hours=1), to_time=now + timedelta(hours=1))
            report("candle upsert is idempotent", len(rows) == 1, f"{len(rows)} row(s)")
        except S.SqlServerUnavailable as exc:
            report("candle upsert is idempotent", False, str(exc))

    signal_id = None
    try:
        signal_id = await repo.signal_create(
            generated_at=now, underlying="ZZTEST", signal_type="BUY_CALL",
            instrument_id=instrument_id, expiry=today + timedelta(days=7),
            strike=25000, option_type="CE", entry=123.45, entry_min=120, entry_max=125,
            stop_loss=95, target1=160, target2=180, risk_reward=1.8, strength=82,
            strategy_version="verify-1.0", spot_at_signal=25010,
            option_ltp_at_signal=123.45, market_trend="BULLISH",
            indicator_snapshot={"probe": True, "rsi": 61.2, "vwap": 24990,
                                "factors": [{"name": "Trend", "score": 20}]},
            reason="verify_sqlserver.py probe row — safe to delete")
        report("usp_Signals_Create", signal_id is not None, f"SignalId={signal_id}")
    except S.SqlServerUnavailable as exc:
        report("usp_Signals_Create", False, str(exc))

    if signal_id:
        try:
            await repo.signal_update_result(
                signal_id=signal_id, status="TARGET1_HIT", exit_price=160,
                exit_time=now, exit_reason="verify probe", result="WIN", pnl=2372.5)
            report("usp_Signals_UpdateResult", True)
        except S.SqlServerUnavailable as exc:
            report("usp_Signals_UpdateResult", False, str(exc))

    paper_id = None
    if instrument_id:
        try:
            paper_id = await repo.paper_create(
                instrument_id=instrument_id, entry_time=now, entry_price=123.45,
                quantity=65, signal_id=signal_id, stop_loss=95, target1=160, target2=180)
            report("usp_PaperTrades_Create", paper_id is not None, f"PaperTradeId={paper_id}")
        except S.SqlServerUnavailable as exc:
            report("usp_PaperTrades_Create", False, str(exc))
    if paper_id:
        try:
            await repo.paper_close(paper_trade_id=paper_id, exit_time=now,
                                   exit_price=160, exit_reason="verify probe", charges=45)
            report("usp_PaperTrades_Close", True)
        except S.SqlServerUnavailable as exc:
            report("usp_PaperTrades_Close", False, str(exc))

    for label, coro in [
        ("usp_AppSettings_Upsert", repo.app_setting_upsert(
            "verify.probe", "ok", description="verify_sqlserver.py probe")),
        ("usp_FeedHealth_Save", repo.feed_health_save(
            source="VERIFY", status="CONNECTED", last_tick=now, reconnects=0,
            response_ms=42, token_status="OK")),
        ("usp_ApplicationLogs_Write", repo.log_write(
            level="INFO", component="VERIFY", message="verify_sqlserver.py probe")),
        ("notifications via ApplicationLogs", repo.notification_write(
            kind="NEW_SIGNAL", title="ZZTEST probe", body="verify probe",
            signal_id=signal_id)),
    ]:
        try:
            await coro
            report(label, True)
        except S.SqlServerUnavailable as exc:
            report(label, False, str(exc))

    try:
        notes = await repo.notifications_get(top=5)
        report("notifications read back", True, f"{len(notes)} notification(s)")
    except S.SqlServerUnavailable as exc:
        report("notifications read back", False, str(exc))


async def check_backtest_writes() -> None:
    print("\n=== 6. Backtest procedures ===")
    caps = await repo.capabilities()
    full = caps.get("usp_BacktestRuns_CreateV2", False)
    print(f"  migration 001 applied: {'YES — full metrics will be stored' if full else 'NO — headline figures only'}")
    today = date.today()
    now = datetime.now(UTC).replace(tzinfo=None)
    run_id = None
    try:
        run_id = await repo.backtest_create(
            run_key=f"verify-{now:%Y%m%d%H%M%S}", start=today - timedelta(days=30),
            end=today, strategy_version="verify-1.0", underlying="ZZTEST",
            timeframe="5m", initial_capital=500000, risk_per_trade_pct=1,
            assumptions={"slippage_pct": 0.1, "brokerage_per_order": 20})
        report("backtest run created", run_id is not None, f"BacktestRunId={run_id}")
    except S.SqlServerUnavailable as exc:
        report("backtest run created", False, str(exc))

    if run_id:
        try:
            await repo.backtest_set_status(run_id=run_id, status="RUNNING")
            report("backtest status -> RUNNING", True)
        except S.SqlServerUnavailable as exc:
            report("backtest status -> RUNNING", False, str(exc))
        try:
            await repo.backtest_trade_insert(
                run_id=run_id, trade_number=1, instrument_id=None, underlying="ZZTEST",
                trading_symbol="ZZTEST25000CE", expiry=today, strike=25000,
                option_type="CE", entry_time=now - timedelta(minutes=30),
                exit_time=now, entry_price=120, exit_price=160, quantity=65,
                stop_loss=95, target1=160, target2=180, gross_pnl=2600, charges=45,
                pnl=2555, r_multiple=1.6, signal_score=82, segment="out_of_sample",
                regime="trend_up", exit_reason="TARGET1")
            report("backtest trade inserted", True)
        except S.SqlServerUnavailable as exc:
            report("backtest trade inserted", False, str(exc))
        try:
            await repo.backtest_complete(
                run_id=run_id,
                metrics={"total_trades": 1, "wins": 1, "losses": 0, "win_rate": 100.0,
                         "gross_pnl": 2600, "total_costs": 45, "net_pnl": 2555,
                         "profit_factor": 9.99, "avg_win": 2555, "avg_loss": 0,
                         "largest_win": 2555, "largest_loss": 0, "avg_r": 1.6,
                         "max_drawdown": 0, "max_drawdown_pct": 0},
                equity_curve=[{"t": str(now), "equity": 502555}])
            report("backtest completed", True)
        except S.SqlServerUnavailable as exc:
            report("backtest completed", False, str(exc))
        try:
            res = await repo.backtest_results(run_id)
            trades = await repo.backtest_trades(run_id)
            report("backtest results read back", bool(res),
                   f"status={res.get('Status')} trades_rows={len(trades)}")
        except S.SqlServerUnavailable as exc:
            report("backtest results read back", False, str(exc))

    print("\n  Probe rows are marked ZZTEST / 'verify probe'. To remove them:")
    print("    DELETE FROM dbo.BacktestTrades WHERE UnderlyingSymbol = 'ZZTEST';")
    print("    DELETE FROM dbo.BacktestRuns   WHERE UnderlyingSymbol = 'ZZTEST';")
    print("    DELETE FROM dbo.PaperTrades    WHERE InstrumentId IN "
          "(SELECT InstrumentId FROM dbo.Instruments WHERE TradingSymbol = 'ZZTEST-VERIFY');")
    print("    DELETE FROM dbo.Signals        WHERE UnderlyingSymbol = 'ZZTEST';")
    print("    DELETE FROM dbo.AppSettings    WHERE SettingKey = 'verify.probe';")


async def main() -> int:
    ap = argparse.ArgumentParser(description="Verify the AngleTrending SQL Server integration")
    ap.add_argument("--write", action="store_true",
                    help="also exercise write procedures using ZZTEST probe rows")
    args = ap.parse_args()

    print("=" * 74)
    print(" AngleTrending SQL Server integration verifier")
    print(" (uses your existing stored procedures only — issues no DDL)")
    print("=" * 74)

    if not await check_connection():
        print("\nRESULT: cannot continue — fix the connection first.")
        return 1
    await check_objects()
    await check_reads()
    if args.write:
        await check_writes()
        await check_backtest_writes()
    else:
        print("\n=== 5. Write procedures ===")
        print(f"{SKIP} skipped — re-run with --write to exercise them")

    print("\n" + "=" * 74)
    if failures:
        print(f"RESULT: {len(failures)} check(s) FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: all checks passed. The application can use this database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
