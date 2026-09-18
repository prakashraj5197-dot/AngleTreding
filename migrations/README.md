# AngleTrending SQL Server integration

The application treats your database as **read/write through existing stored procedures
only**. It issues no DDL: no CREATE, ALTER, DROP or RENAME, and no ad-hoc INSERT/UPDATE
against a table. Any schema change you see requested here arrives as a migration script
for you to review and run manually.

## 1. Pending migration

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

## 2. Point the backend at your SQL Server

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

## 3. Verify before running the app

```
cd backend
python verify_sqlserver.py            # read-only: connection + inventory + read procs
python verify_sqlserver.py --write    # also exercises every write proc with ZZTEST rows
```

It checks all 15 tables and 31 procedures the app depends on, reports whether migration
001 is applied, confirms candle upserts are idempotent, and prints DELETE statements for
the probe rows it created.

## 4. Cloud preview vs your machine

The hosted preview cannot reach a LAN instance, so it stays on `DB_BACKEND=mongo` for
demos. Switching to `sqlserver` is a `.env` change plus a backend restart — no code edit:

```
sudo supervisorctl restart backend
```
