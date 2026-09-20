# QuantPulse F&O Signal & Backtesting Engine — living spec

## What the app does
Web-based F&O (futures & options) market analysis and signal-generation system for NSE
NIFTY / BANK NIFTY. It ingests a live market feed, scores market direction from multiple
independent factors, selects a CALL or PUT contract, computes entry/SL/targets, enforces
risk limits, tracks each signal's lifecycle to its result, and can replay the identical
strategy over ~2 years of stored history. Paper trading only — **no real orders, ever**.

Stack: FastAPI + motor/MongoDB backend, Vite + React 19 + TS strict frontend (dark
"obsidian terminal" theme). Delivered on the pod stack rather than the ASP.NET/Angular/SQL
Server named in the brief; the layered separation (provider → engines → routers → UI) and
provider-behind-an-interface requirement are preserved.

## Market data provider (swappable)
`backend/lib/sim_provider.py` — `MarketDataProvider` ABC + `SimulatedProvider`, a
deterministic seeded NSE-style feed (the only v1 provider; a broker feed implements the
same ABC). Generates 1m candles → 5m/15m aggregates, live quotes with intra-minute
interpolation, and full option chains (ATM±10 strikes, 3 weeklies + monthlies for NIFTY)
with an IV smile, Black-Scholes greeks, volume/OI/ΔOI, bid/ask spreads, PCR, max pain,
futures price/basis. Same (symbol, day, anchor) ⇒ same data, so backtests reproduce.
Session modes: `always_on` (continuous simulated session, default) or `market_hours`
(honours the real 09:15–15:30 IST clock incl. weekends → MARKET CLOSED).

## Data model (MongoDB)
| Collection | Contents |
|---|---|
| `candles` | OHLCV per (symbol, timeframe, ts) — unique index = tick/bar dedupe. 1m/5m/15m, ~2 yrs for NIFTY + BANKNIFTY |
| `signals` | every generated signal + full audit snapshot (indicators, option greeks/liquidity, F&O structure, risk sizing, rejected candidates, strategy version, event log) |
| `engine_state` | latest evaluation per symbol: direction, score, factors, no-trade reason, indicators |
| `option_chain_snapshots` | timestamped chain captures (~15 min cadence) |
| `paper_positions`, `paper_account` | virtual positions + ledger |
| `backtest_jobs`, `backtest_trades` | job status/metrics/equity curve + trade-by-trade log |
| `notifications` | new-signal / target / SL / expiry alerts |
| `settings` (`_id: app`), `sim_state`, `sessions` | config, per-session sim anchor, admin cookies |

Timestamps are UTC-aware in Mongo; IST (Asia/Kolkata) is the single display timezone.

## Engines (pure functions — same code live and in backtests)
- **Direction** (`lib/engine.py::evaluate_direction`): weighted factors — trend (EMA
  20/50/200), VWAP deviation, momentum (RSI + MACD), breakout/breakdown vs N-bar range with
  volume confirmation, relative volume, F&O positioning (PCR, futures ΔOI build-up, basis).
  Signed score −100..100 → BULLISH / BEARISH / SIDEWAYS / NO_TRADE. Technical-vs-F&O
  disagreement beyond tolerance ⇒ NO_TRADE. Every verdict carries per-factor reasons.
- **Option selection**: CE on bullish / PE on bearish, ATM±N window, hard rejects on OI,
  volume, spread % and premium floors; weighted score (liquidity, moneyness, OI alignment,
  IV band, spread). Best contract must clear the minimum score or ⇒ NO TRADE.
- **Levels**: entry band around mid, SL from premium %/spread floor, T1 blended with
  delta×ATR expected move, T2 at an R multiple; rejects when no valid SL or R:R < minimum.
- **Risk** (`lib/risk.py`): daily loss limit, consecutive losses, max trades/day, one
  active signal per symbol, cooldown, one re-entry/day. Blocked ⇒ NO TRADE with the reason.

## Lifecycle
GENERATED → ACTIVE → (entry must fill inside the band, else EXPIRED/MISSED ENTRY after the
validity window) → TARGET1_HIT → TARGET2_HIT, or STOP_LOSS, or session SQUARE_OFF; plus
CANCELLED / DATA_ERROR. A 5s monitor loop tracks fills, SL/targets and paper positions; a
60s loop runs evaluations (cooldown + one-active-signal gates keep new-signal cadence sane).

## Backtesting (look-ahead free)
`lib/backtest.py`: iterates stored candles; the decision at candle close T uses only
indicator values ≤ T and a chain synthesised at T; entry is the **next** candle's open with
slippage. SL/target checked on Black-Scholes option candles; when both fall in one candle
the conservative rule treats SL as hit first. Costs = slippage + brokerage/order + charges %;
gross, costs and net P&L are reported separately. Trades are tagged development /
validation / out-of-sample (60/20/20) and a warning fires under 200 trades. Metrics include
win rate, profit factor, max drawdown, avg R, largest win/loss, CALL vs PUT, monthly and
per-regime breakdowns. Jobs run in the background: QUEUED → RUNNING → COMPLETED/FAILED.

## Pages
`/` Dashboard · `/signals` Live Signals & history (+ detail drawer) · `/option-scanner`
chain + ranking · `/market-analysis` technical/F&O decomposition · `/backtesting` ·
`/paper-trading` · `/settings` (auth-gated writes).

## Auth
Single admin, httpOnly cookie session (`fno_session`, 12 h) — see
`memory/test_credentials.md`. Settings are readable by anyone; **mutations require the
admin**. Provider/broker credentials live only in `backend/.env`, never sent to the client.
Saving any strategy parameter change auto-mints a new strategy version (old signals are
never rewritten).

## Key API routes (all under /api)
`/market/status|instruments|quotes|quote/{symbol}|candles/{symbol}|chain/{symbol}|freshness`,
`/health`, `/engine/state`, `/engine/evaluate`, `/signals`, `/signals/active`,
`/signals/analytics`, `/signals/{id}`, `/signals/{id}/cancel`, `/scanner/{symbol}`,
`/backtest/dataset|run|jobs|jobs/{id}|jobs/{id}/trades`, `/paper/account|positions|execute/{id}|close/{id}|reset`,
`/notifications`, `/notifications/read-all`, `/settings` (GET/PUT), `/settings/reset`,
`/auth/login|logout|me`.

## Seed facts
`cd /app/backend && python seed.py --days 520 [--reset]` → NIFTY & BANKNIFTY, 195,000 1m /
39,000 5m / 13,000 15m candles each (~2 years), default settings, ₹500,000 paper account.
`cd /app/backend && python seed_signals.py --sessions 30 [--reset]` → replays the last ~30
sessions through the LIVE engine pipeline (same direction → option → levels → risk gates,
data ≤ decision timestamp) and stores the resulting signals with full audit snapshots,
resolved lifecycle outcomes, matching closed paper positions and a notification trail.
54 signals / 54 closed paper positions currently seeded. Nothing here is fabricated —
every row is engine output. On any given live day the engine may legitimately sit at
NO TRADE; an empty *active* signal list with a stated reason is correct behaviour.

## Market-data providers (swappable)
`lib/provider_registry.py` is the single place that decides the live vendor;
`settings.data.provider` (`simulated` | `angelone`) selects it and `get_provider()` in
`lib/signal_engine.py` resolves it. Both implementations satisfy the same surface
(`get_quote`, `build_chain`, `today_candles`, `next_expiries`, `get_status`), so no engine
code knows which feed is attached.

- **simulated** (default) — `lib/sim_provider.py`. Deterministic synthetic NSE feed with an
  always-on session. Also powers backtest replay for BOTH providers.
- **angelone** — `lib/broker_angelone.py`. Real Angel One SmartAPI feed:
  - Session: `SmartConnect.generateSession(client_code, mpin, pyotp TOTP)`; the jwt is
    cached and re-minted on `AG8001/AG8002/AB1010/AB8050` or after ~20h.
  - Instruments: the public `OpenAPIScripMaster.json` dump is downloaded once per day and
    filtered to NIFTY/BANKNIFTY index tokens (26000 / 26009), OPTIDX contracts and FUTIDX.
    Verified live: 1,700 NIFTY option contracts across 18 expiries.
  - Lot sizes are taken from the broker's master and override the static table
    (NIFTY 75 → 65, BANKNIFTY 35 → 30 as of Sept 2026) so live sizing is correct.
  - Quotes/chain use `getMarketData("FULL", …)` in ≤50-token batches (OI, bid/ask depth,
    `avgPrice` as VWAP); candles use `getCandleData` with ONE/FIVE/FIFTEEN_MINUTE.
  - SmartAPI publishes **no IV or greeks**, so both are derived locally from the premium
    (`lib/option_math.implied_vol` + `bs_greeks`). An unsolvable premium yields iv=0 and
    zero greeks rather than an invented value (AC-72).
  - Credentials live ONLY in backend/.env (`ANGELONE_API_KEY`, `ANGELONE_CLIENT_CODE`,
    `ANGELONE_MPIN`, `ANGELONE_TOTP_SECRET`) and are never returned by any endpoint.

### Fail-safe contract (user's explicit choice)
A failing live feed NEVER falls back to simulated prices. The adapter raises
`ProviderUnavailable`; a FastAPI handler turns that into **503** on data endpoints, while
status endpoints (`/api/health`, `/api/market/status`, `/api/market/freshness`) stay 200 and
report the degraded truth. The engine writes a `NO_TRADE` state with
"🔴 DATA FEED DISCONNECTED — SIGNAL GENERATION PAUSED" plus the missing env vars, the
monitor leaves ACTIVE signals untouched, and the UI shows FEED DISCONNECTED / DATA STALE.
Switching provider triggers an immediate re-evaluation and sets the session mode to match
(`angelone` → real NSE hours, `simulated` → always-on demo).
Routes: `GET /api/provider/status`, `POST /api/provider/select/{name}`,
`POST /api/provider/test`, `POST /api/provider/instruments/refresh` (all mutations admin-only).

## Calibration decisions (measured, not guessed)
Two spec defaults were measured against the seeded history and adjusted, because the
literal values made the system incapable of ever producing a signal. Both stay fully
configurable on the Settings page — this is the §31/§36.40 "validate thresholds on
historical data" loop, not a silent override.

1. **Minimum signal score: 70 → 50.** Over 6 months of NIFTY 5m data the |direction score|
   distribution is p50≈26, p90≈45, p95≈50, max≈74. A threshold of 70 qualified 0.1% of
   bars (≈0 trades); 50 qualifies the top ~5%. Strength bands are therefore *relative* to
   the configured minimum (`strength_label(score, min_score)`): Moderate ≥min,
   Strong ≥min+12, Very Strong ≥min+25.
2. **Risk capital: ₹11,000 / ₹110 per trade → ₹5,00,000 / ₹5,000.** The spec's ratios
   (1% risk/trade, 2% daily loss, 3 consecutive losses) are preserved exactly, but one
   NIFTY lot (75) at ~₹6.5 premium risk needs ≈₹490, so a ₹110 cap always rounded position
   size to zero and no trade could ever be taken. When a qualifying setup still cannot fund
   one lot, the backtest reports it as an explicit warning instead of dropping it silently.

## Bug fixes worth remembering
- `select_option` must receive `ist_now` in backtests; otherwise time-to-expiry uses the
  real clock and every historical contract looks expired (this silently zeroed all trades).
- Moneyness scoring normalises a rupee distance → divide by `atm_range × strike_step`,
  never by the strike count.
- Mongo returns naive datetimes; normalise to UTC before comparing with provider
  timestamps (`load_series`, lifecycle monitor).
- The backtest computes cheap `chain_summary()` aggregates per candle and builds a fully
  priced chain only when direction qualifies — a 2-year run went from >60s to ~20s.
- Recharts stacked candle bars force 0 into the Y domain; `allowDataOverflow` on the
  YAxis keeps the price scale readable.

## Deliberate deviations from the brief
- Stack is FastAPI/React/MongoDB (pod default), not ASP.NET Core/Angular/SQL Server.
- Market data defaults to the built-in deterministic simulator; the Angel One SmartAPI
  adapter is implemented and selectable but needs real credentials in backend/.env.
- Historical option contracts are synthesised deterministically at each historical
  timestamp rather than stored row-by-row, keeping the dataset reproducible and compact.
  This holds for BOTH providers — backtesting always replays stored candles, never a live feed.
- Notifications are in-app (bell + toasts) only; Telegram/email/push are left as future
  channels behind the same `notify()` seam.
- Live ticks use REST polling, not SmartWebSocketV2 streaming.

## Data store: AngleTrending SQL Server (local/prod) vs MongoDB (preview)
`DB_BACKEND` in backend/.env is the ONE switch and it moves the entire application:
`sqlserver` → the user's AngleTrending database; `mongo` (default) → MongoDB, used only
because the hosted preview cannot reach a LAN SQL Server. Switching is a .env change plus
`sudo supervisorctl restart backend` — no code edit, no per-feature toggle.

- `lib/db.py` resolves `db` to either the motor handle or `lib/store.py`'s `SqlStore`.
  Every router, engine, script and test imports that one handle, so both stores serve
  100% of the app's reads/writes.
- `lib/store.py` — SQL Server document store implementing the motor subset the codebase
  uses (find/find_one/count_documents/insert_one/insert_many/update_one/update_many/
  replace_one/delete_one/delete_many/bulk_write/drop; operators `$set $in $nin $gte $gt
  $lte $lt $ne`; an unsupported operator raises instead of returning wrong rows). Storage
  is one additive `dbo.Fno*` table per collection: full record in a `Doc` JSON column
  (datetimes keep their timezone) plus typed indexed columns for every filtered/sorted
  field. Candle seeding goes through a #temp staging table + MERGE, so ~250k rows is a
  handful of round-trips. `COLUMNS`/`UNIQUE`/`INDEXES` in this module are the single
  source of truth: `backend/gen_store_schema.py` generates
  `migrations/002_app_store.sql` from them.
- `migrations/002_app_store.sql` — REQUIRED for sqlserver mode; creates the 12 `Fno*`
  tables + indexes, guarded so re-running is safe. `/api/database/status` reports
  `store_tables_missing` and the UI (Settings → Data store) shows it as pending.
- `backend/tests/test_store_sql.py` — 27 tests asserting the generated T-SQL/params for
  every query shape the app issues (no database needed), plus a DDL-refusal check.
- `verify_sqlserver.py` adds a live CRUD round-trip through the store against the real
  database (insert → read → `$set` → count → sorted page → delete + idempotent bulk
  candle upsert).

**Hard constraint from the user: the application must never create, drop, rename or alter a
database object.** All SQL access goes through the stored procedures that already exist.
Any schema need is delivered as a migration script in `/app/migrations` for the user to run
manually; only then is the app code updated to use it.

- `lib/sqlserver.py` — env-driven ODBC config, per-call pyodbc connections executed on a
  worker thread, `call_proc()` (parameterised EXEC; only the proc *name* is interpolated and
  every call site passes a literal), read-only `select()` for metadata, and `health()` which
  never raises. Passwords are never logged (`connection_string(redacted=True)`) and never
  leave the backend.
- `lib/repo_sql.py` — 38 async functions mapping every app operation onto the 31 existing
  procedures, plus the 6 optional ones from migration 001. Highlights:
  - Instruments are upserted per traded contract (`usp_Instruments_Upsert`) with a
    symbol→InstrumentId cache, so signals/paper trades carry a real FK and expired
    contracts keep their identity (§36.7).
  - The full signal audit payload (indicator values, per-factor direction breakdown, option
    snapshot with greeks, rejected candidates, risk inputs) is serialised into
    `Signals.IndicatorSnapshot` as JSON (§23).
  - Settings split as the schema intends: strategy parameters →
    `usp_Strategies_SaveParameter`; risk/data/option config → `usp_AppSettings_Upsert`.
  - Notifications reuse `dbo.ApplicationLogs` with `Component='NOTIFICATION'` (no schema
    change); `CorrelationId` carries the SignalId so duplicates are detectable (AC-64).
  - Backtest writes prefer the `_V2` procs and **fall back to the originals when migration
    001 has not been run**, logging the shortfall instead of inventing columns.
- `routers/database.py` — `GET /api/database/status` (backend, connectivity, table/proc
  counts, pending migrations; no secrets) and `GET /api/database/capabilities` (admin only).
  Surfaced in Settings → Data & notifications → "Data store".
- `backend/verify_sqlserver.py` — run on the user's machine: checks connection, inventories
  all 15 tables / 31 procs, exercises every read proc, and with `--write` exercises every
  write proc using `ZZTEST` probe rows (then prints DELETE statements for them). Confirms
  candle upsert idempotency (AC-03).

### Known gap (needs a proc, not yet requested)
`dbo.SignalHistory` has no insert procedure in the user's schema, so the per-event lifecycle
trail is currently written to `ApplicationLogs`; signal status/exit itself is persisted via
`usp_Signals_UpdateResult`. A `usp_SignalHistory_Write` proc would be migration 002.

### Still to wire (SQL mode)
The repository and verifier are complete, but the engine/backtest/router call sites still
read and write through motor. Porting them is gated on the user confirming connectivity and
migration 001 from their machine, since none of it can be executed from the cloud preview.
