# AngleTrending SQL Server integration

The application issues **no DDL**: no CREATE, ALTER, DROP or RENAME, ever. It reads and
writes only (a) your existing stored procedures and (b) the additive `dbo.Fno*` tables
created by `002_app_store.sql`. Any schema change arrives here as a script for you to
review and run manually.

## 0. ONE SWITCH — make the whole system run on SQL Server

1. Run **`002_app_store.sql`** (and optionally `001_...sql`) against `AngleTrending`.
2. Set **`DB_BACKEND=sqlserver`** in `backend/.env` (plus the `SQLSERVER_*` values below).
3. Restart the backend.

That is the only change. Every read and write in the application — signals, candles,
option-chain snapshots, engine state, notifications, paper positions, backtest jobs and
trades, settings, login sessions — then goes to SQL Server. MongoDB is used only when
`DB_BACKEND=mongo` (the cloud preview, which cannot reach a LAN instance).

Settings → Data store shows which store is live, whether the tables are present, and
which migrations are still pending.

## 1. Migration 002 — application store (REQUIRED for SQL Server mode)

`002_app_store.sql` — **additive and idempotent**.

* Creates 12 new tables, all prefixed `Fno` so they cannot collide with anything you
  already have: `FnoSettings`, `FnoPaperAccount`, `FnoCandles`, `FnoSignals`,
  `FnoEngineState`, `FnoSimState`, `FnoOptionChainSnapshots`, `FnoNotifications`,
  `FnoPaperPositions`, `FnoBacktestJobs`, `FnoBacktestTrades`, `FnoSessions`.
* Each table keeps the full record in a `Doc` (JSON) column plus typed, **indexed**
  columns for every field the app filters or sorts on (symbol, timeframe, ts, status,
  day_ist, score, created_at, …), so queries use real indexes.
* Creates the unique keys that enforce deduplication — e.g. one candle per
  (symbol, timeframe, ts) (AC-03) and one row per SignalId (AC-24).
* Every statement is guarded by an existence check: **re-running it is safe**, and no
  existing table, view, procedure or row is touched.
* The file is generated from `backend/lib/store.py` by `backend/gen_store_schema.py`,
  so the schema and the application can never drift apart.

Run it with:

```
sqlcmd -S "PRAKASHPC\SQLEXPRESS" -d AngleTrending -E -i 002_app_store.sql
```

or open it in SSMS with `AngleTrending` as the active database. It prints one line per
object created and ends with a list of the tables and their row counts.

## 2. Optional migration 001 — extended backtest reporting

`001_backtest_reporting_columns.sql` — **additive and idempotent**.

* Adds 17 nullable columns to `dbo.BacktestRuns` and 13 to `dbo.BacktestTrades`
  (gross vs net P&L, total costs, profit factor, avg/largest win & loss, avg R,
  timeframe, symbol, equity-curve JSON, assumptions JSON, plus per-trade side CE/PE,
  target2, R multiple, dataset segment, market regime, charges).
* Adds 6 **new** procedures: `usp_BacktestRuns_CreateV2`, `_CompleteV2`, `_SetStatus`,
  `_GetList`, `usp_BacktestTrades_InsertV2`, `_GetByRun`.
* Adds one filtered unique index (`RunKey`), one check constraint (`OptionType IN ('CE','PE')`,
  `WITH NOCHECK` so existing rows are untouched) and one covering index.
* **Nothing existing is modified.** Your `usp_BacktestRuns_Create`, `usp_BacktestTrades_Insert`,
  `usp_BacktestRuns_Complete` and `usp_BacktestRuns_GetResults` keep working unchanged.
* Re-running the script is safe — every statement is guarded.

Run it with:

```
sqlcmd -S "PRAKASHPC\SQLEXPRESS" -d AngleTrending -E -i 001_backtest_reporting_columns.sql
```

The app works **before** you run it: it detects the missing procedures at runtime and
falls back to your original ones, storing the headline figures only. The Settings →
Data store panel shows a "Pending migration" notice until the script has been applied.

## 3. Point the backend at your SQL Server

Edit `backend/.env`:

```
DB_BACKEND=sqlserver
SQLSERVER_HOST=PRAKASHPC\SQLEXPRESS
SQLSERVER_DATABASE=AngleTrending
SQLSERVER_TRUSTED=1          # Windows auth; leave USER/PASSWORD blank
# or, for SQL auth:
# SQLSERVER_TRUSTED=0
# SQLSERVER_USER=sa
# SQLSERVER_PASSWORD=********
SQLSERVER_DRIVER=ODBC Driver 18 for SQL Server
SQLSERVER_ENCRYPT=no
SQLSERVER_TRUST_CERT=yes
```

Prerequisite: **ODBC Driver 18 for SQL Server** on the machine running the backend
(Windows: "Microsoft ODBC Driver 18 for SQL Server"; Linux: `msodbcsql18` + `unixodbc`).

These values are read server-side only (`os.environ`) and are never returned by an API
or bundled into the frontend. `GET /api/database/status` exposes host/database name,
connectivity and object counts — never a password.

## 4. Verify before running the app

```
cd backend
python verify_sqlserver.py            # read-only: connection + inventory + read procs
python verify_sqlserver.py --write    # also exercises every write proc with ZZTEST rows
```

It checks all 15 tables and 31 procedures the app depends on, checks the 12 `Fno*`
store tables from migration 002, performs a live CRUD round-trip through the store
(insert → read → `$set` update → count → sorted page → delete, plus an idempotent bulk
candle upsert), reports whether migration 001 is applied, and prints DELETE statements
for the probe rows it created.

## 5. Cloud preview vs your machine

The hosted preview cannot reach a LAN instance, so it stays on `DB_BACKEND=mongo` for
demos. Switching to `sqlserver` is a `.env` change plus a backend restart — no code edit:

```
sudo supervisorctl restart backend
```
