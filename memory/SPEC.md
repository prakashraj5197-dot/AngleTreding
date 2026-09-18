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
- Market data is the built-in deterministic simulator (user-approved), not a live broker API.
- Historical option contracts are synthesised deterministically at each historical
  timestamp rather than stored row-by-row, keeping the dataset reproducible and compact.
- Notifications are in-app (bell + toasts) only; Telegram/email/push are left as future
  channels behind the same `notify()` seam.
