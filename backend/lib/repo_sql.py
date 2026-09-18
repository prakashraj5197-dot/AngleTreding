"""AngleTrending SQL Server repository.

Every function here maps one application operation onto the stored procedures that
ALREADY exist in the database. Nothing in this module issues DDL: no CREATE, ALTER,
DROP or RENAME, and no ad-hoc INSERT/UPDATE against a table. If an operation cannot
be expressed with an existing procedure it is reported in `capabilities()` so the
application can degrade honestly instead of silently writing nothing.

Procedures used (all pre-existing):
    Instruments  : usp_Instruments_GetActive / _GetBySymbolToken / _Upsert
    Ticks        : usp_MarketTicks_Insert / _GetLatest
    Candles      : usp_MarketCandles_Upsert / _Get
    Option chain : usp_OptionChain_SaveSnapshot / _GetLatest
    Strategies   : usp_Strategies_GetActive / _GetParameters / _SaveParameter
    Signals      : usp_Signals_Create / _GetLatest / _GetHistory / _UpdateResult
    Paper        : usp_PaperTrades_Create / _Close / _GetOpen / _GetHistory / _GetPnLSummary
    Backtest     : usp_BacktestRuns_Create / _Complete / _GetResults, usp_BacktestTrades_Insert
    Settings     : usp_AppSettings_Get / _Upsert
    Ops          : usp_FeedHealth_Save, usp_ApplicationLogs_Write / _Get

Added by migrations/001 (optional — detected at runtime, never assumed):
    usp_BacktestRuns_CreateV2 / _CompleteV2 / _SetStatus / _GetList
    usp_BacktestTrades_InsertV2 / usp_BacktestTrades_GetByRun
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from lib.sqlserver import SqlServerUnavailable, call_proc

logger = logging.getLogger("quantpulse.repo.sql")

# in-process cache: TradingSymbol -> InstrumentId (the dump is stable within a day)
_instrument_ids: dict[str, int] = {}
_proc_cache: dict[str, bool] = {}


async def proc_exists(name: str) -> bool:
    """True when the procedure is present, so migration-dependent paths stay optional."""
    if name in _proc_cache:
        return _proc_cache[name]
    rows = await call_proc(
        "sp_executesql",
        stmt="SELECT CASE WHEN OBJECT_ID(@n, 'P') IS NULL THEN 0 ELSE 1 END AS Present",
        params="@n NVARCHAR(200)",
        n=name,
    )
    present = bool(rows and list(rows[0].values())[0])
    _proc_cache[name] = present
    return present


async def capabilities() -> dict[str, bool]:
    """Which optional (migration-provided) procedures this database currently has."""
    names = [
        "dbo.usp_BacktestRuns_CreateV2",
        "dbo.usp_BacktestRuns_CompleteV2",
        "dbo.usp_BacktestRuns_SetStatus",
        "dbo.usp_BacktestRuns_GetList",
        "dbo.usp_BacktestTrades_InsertV2",
        "dbo.usp_BacktestTrades_GetByRun",
    ]
    out: dict[str, bool] = {}
    for n in names:
        try:
            out[n.split(".")[-1]] = await proc_exists(n)
        except SqlServerUnavailable:
            out[n.split(".")[-1]] = False
    return out


def _jsonify(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str)


# --------------------------------------------------------------------------- #
# instruments
# --------------------------------------------------------------------------- #

async def instruments_active() -> list[dict[str, Any]]:
    return await call_proc("dbo.usp_Instruments_GetActive")


async def instrument_by_symbol(trading_symbol: str | None = None,
                               symbol_token: str | None = None) -> dict[str, Any] | None:
    rows = await call_proc(
        "dbo.usp_Instruments_GetBySymbolToken",
        TradingSymbol=trading_symbol, SymbolToken=symbol_token)
    return rows[0] if rows else None


async def instrument_upsert(*, exchange: str, trading_symbol: str, instrument_type: str,
                            segment: str | None = None, symbol_token: str | None = None,
                            underlying: str | None = None, expiry: date | None = None,
                            strike: float | None = None, option_type: str | None = None,
                            lot_size: int | None = None, tick_size: float | None = None,
                            is_active: bool = True) -> int | None:
    """Upsert an instrument and return its InstrumentId.

    Called for every traded option contract so Signals/PaperTrades can carry a real
    FK and expired contracts keep their identity (spec §36.7).
    """
    rows = await call_proc(
        "dbo.usp_Instruments_Upsert",
        Exchange=exchange, Segment=segment, TradingSymbol=trading_symbol,
        SymbolToken=symbol_token, UnderlyingSymbol=underlying,
        InstrumentType=instrument_type, ExpiryDate=expiry, StrikePrice=strike,
        OptionType=option_type, LotSize=lot_size, TickSize=tick_size,
        IsActive=1 if is_active else 0)
    iid = None
    if rows:
        for key in ("InstrumentId", "instrumentid", "Id"):
            if key in rows[0]:
                iid = rows[0][key]
                break
        if iid is None:
            iid = list(rows[0].values())[0]
    if iid is None:  # the proc may not project the id — read it back
        found = await instrument_by_symbol(trading_symbol=trading_symbol)
        iid = found.get("InstrumentId") if found else None
    if iid is not None:
        _instrument_ids[trading_symbol] = int(iid)
        return int(iid)
    return None


async def resolve_instrument_id(trading_symbol: str, **upsert_kwargs: Any) -> int | None:
    """Cached symbol -> InstrumentId, upserting on first use."""
    if trading_symbol in _instrument_ids:
        return _instrument_ids[trading_symbol]
    found = await instrument_by_symbol(trading_symbol=trading_symbol)
    if found and found.get("InstrumentId") is not None:
        _instrument_ids[trading_symbol] = int(found["InstrumentId"])
        return _instrument_ids[trading_symbol]
    if not upsert_kwargs:
        return None
    return await instrument_upsert(trading_symbol=trading_symbol, **upsert_kwargs)


# --------------------------------------------------------------------------- #
# market data
# --------------------------------------------------------------------------- #

async def tick_insert(*, instrument_id: int, ts: datetime, ltp: float | None = None,
                      open_: float | None = None, high: float | None = None,
                      low: float | None = None, close: float | None = None,
                      volume: float | None = None, oi: int | None = None,
                      last_qty: int | None = None, bid: float | None = None,
                      bid_qty: int | None = None, ask: float | None = None,
                      ask_qty: int | None = None, source: str | None = None) -> None:
    await call_proc(
        "dbo.usp_MarketTicks_Insert",
        InstrumentId=instrument_id, ExchangeTimestamp=ts, LTP=ltp, OpenPrice=open_,
        HighPrice=high, LowPrice=low, ClosePrice=close, Volume=volume, OpenInterest=oi,
        LastTradedQuantity=last_qty, BidPrice=bid, BidQuantity=bid_qty,
        AskPrice=ask, AskQuantity=ask_qty, DataSource=source)


async def ticks_latest(instrument_id: int, *, from_time: datetime | None = None,
                       to_time: datetime | None = None, top: int = 100) -> list[dict[str, Any]]:
    return await call_proc(
        "dbo.usp_MarketTicks_GetLatest",
        InstrumentId=instrument_id, FromTime=from_time, ToTime=to_time, TopRows=top)


async def candle_upsert(*, instrument_id: int, timeframe: str, start: datetime,
                        o: float, h: float, l: float, c: float,
                        volume: float | None = None, oi: int | None = None) -> None:
    """Idempotent by (InstrumentId, TimeFrame, CandleStartTime) — satisfies AC-03."""
    await call_proc(
        "dbo.usp_MarketCandles_Upsert",
        InstrumentId=instrument_id, TimeFrame=timeframe, CandleStartTime=start,
        OpenPrice=o, HighPrice=h, LowPrice=l, ClosePrice=c, Volume=volume, OpenInterest=oi)


async def candles_get(*, instrument_id: int, timeframe: str,
                      from_time: datetime, to_time: datetime) -> list[dict[str, Any]]:
    return await call_proc(
        "dbo.usp_MarketCandles_Get",
        InstrumentId=instrument_id, TimeFrame=timeframe, FromTime=from_time, ToTime=to_time)


async def option_chain_save_row(*, instrument_id: int | None, underlying: str,
                                snapshot_time: datetime, expiry: date, strike: float,
                                option_type: str, spot: float | None = None,
                                ltp: float | None = None, o: float | None = None,
                                h: float | None = None, l: float | None = None,
                                c: float | None = None, volume: float | None = None,
                                oi: int | None = None, change_in_oi: int | None = None,
                                iv: float | None = None, delta: float | None = None,
                                gamma: float | None = None, theta: float | None = None,
                                vega: float | None = None, bid: float | None = None,
                                bid_qty: int | None = None, ask: float | None = None,
                                ask_qty: int | None = None, source: str | None = None) -> None:
    await call_proc(
        "dbo.usp_OptionChain_SaveSnapshot",
        InstrumentId=instrument_id, UnderlyingSymbol=underlying, SnapshotTime=snapshot_time,
        ExpiryDate=expiry, StrikePrice=strike, OptionType=option_type, SpotPrice=spot,
        LTP=ltp, OpenPrice=o, HighPrice=h, LowPrice=l, ClosePrice=c, Volume=volume,
        OpenInterest=oi, ChangeInOI=change_in_oi, ImpliedVolatility=iv, Delta=delta,
        Gamma=gamma, Theta=theta, Vega=vega, BidPrice=bid, BidQuantity=bid_qty,
        AskPrice=ask, AskQuantity=ask_qty, DataSource=source)


async def option_chain_latest(underlying: str, *, expiry: date | None = None,
                              snapshot_time: datetime | None = None) -> list[dict[str, Any]]:
    return await call_proc(
        "dbo.usp_OptionChain_GetLatest",
        UnderlyingSymbol=underlying, ExpiryDate=expiry, SnapshotTime=snapshot_time)


# --------------------------------------------------------------------------- #
# strategies & settings
# --------------------------------------------------------------------------- #

async def strategies_active() -> list[dict[str, Any]]:
    return await call_proc("dbo.usp_Strategies_GetActive")


async def strategy_parameters(strategy_id: int) -> dict[str, str]:
    rows = await call_proc("dbo.usp_Strategies_GetParameters", StrategyId=strategy_id)
    out: dict[str, str] = {}
    for r in rows:
        name = r.get("ParameterName")
        if name is not None:
            out[str(name)] = r.get("ParameterValue")
    return out


async def strategy_save_parameter(strategy_id: int, name: str, value: Any,
                                  description: str | None = None) -> None:
    await call_proc(
        "dbo.usp_Strategies_SaveParameter",
        StrategyId=strategy_id, ParameterName=name,
        ParameterValue=str(value), Description=description)


async def app_settings_get(key: str | None = None) -> dict[str, Any]:
    rows = await call_proc("dbo.usp_AppSettings_Get", SettingKey=key)
    return {str(r.get("SettingKey")): r.get("SettingValue") for r in rows
            if r.get("SettingKey") is not None}


async def app_setting_upsert(key: str, value: Any, *, is_secret: bool = False,
                             description: str | None = None) -> None:
    await call_proc(
        "dbo.usp_AppSettings_Upsert",
        SettingKey=key, SettingValue=str(value),
        IsSecret=1 if is_secret else 0, Description=description)


# --------------------------------------------------------------------------- #
# signals
# --------------------------------------------------------------------------- #

async def signal_create(*, generated_at: datetime, underlying: str, signal_type: str,
                        instrument_id: int | None = None, expiry: date | None = None,
                        strike: float | None = None, option_type: str | None = None,
                        entry: float | None = None, entry_min: float | None = None,
                        entry_max: float | None = None, stop_loss: float | None = None,
                        target1: float | None = None, target2: float | None = None,
                        risk_reward: float | None = None, strength: float | None = None,
                        strategy_id: int | None = None, strategy_version: str | None = None,
                        spot_at_signal: float | None = None,
                        option_ltp_at_signal: float | None = None,
                        market_trend: str | None = None,
                        indicator_snapshot: Any = None,
                        reason: str | None = None) -> int | None:
    """Insert a signal and return its SignalId.

    `indicator_snapshot` is serialised to JSON and holds the complete audit payload the
    spec requires (§23): indicator values, the per-factor direction breakdown, the option
    snapshot with greeks, the rejected candidates and the risk inputs.
    """
    rows = await call_proc(
        "dbo.usp_Signals_Create",
        GeneratedAt=generated_at, InstrumentId=instrument_id, UnderlyingSymbol=underlying,
        ExpiryDate=expiry, StrikePrice=strike, OptionType=option_type,
        SignalType=signal_type, EntryPrice=entry, EntryMinPrice=entry_min,
        EntryMaxPrice=entry_max, StopLossPrice=stop_loss, Target1Price=target1,
        Target2Price=target2, RiskReward=risk_reward, StrengthScore=strength,
        StrategyId=strategy_id, StrategyVersion=strategy_version,
        SpotPriceAtSignal=spot_at_signal, OptionLTPAtSignal=option_ltp_at_signal,
        MarketTrend=market_trend, IndicatorSnapshot=_jsonify(indicator_snapshot),
        SignalReason=reason)
    if not rows:
        return None
    for key in ("SignalId", "signalid", "Id"):
        if key in rows[0]:
            return int(rows[0][key])
    val = list(rows[0].values())[0]
    return int(val) if val is not None else None


async def signals_latest(*, top: int = 20, underlying: str | None = None,
                         strategy_id: int | None = None) -> list[dict[str, Any]]:
    return await call_proc(
        "dbo.usp_Signals_GetLatest",
        TopRows=top, UnderlyingSymbol=underlying, StrategyId=strategy_id)


async def signals_history(*, from_time: datetime, to_time: datetime,
                          underlying: str | None = None, strategy_id: int | None = None,
                          status: str | None = None) -> list[dict[str, Any]]:
    return await call_proc(
        "dbo.usp_Signals_GetHistory",
        FromTime=from_time, ToTime=to_time, UnderlyingSymbol=underlying,
        StrategyId=strategy_id, Status=status)


async def signal_update_result(*, signal_id: int, status: str,
                               exit_price: float | None = None,
                               exit_time: datetime | None = None,
                               exit_reason: str | None = None,
                               result: str | None = None,
                               pnl: float | None = None) -> None:
    """Lifecycle transition: ACTIVE -> TARGET1_HIT / STOP_LOSS / EXPIRED / ... (AC-28..31)."""
    await call_proc(
        "dbo.usp_Signals_UpdateResult",
        SignalId=signal_id, Status=status, ExitPrice=exit_price, ExitTime=exit_time,
        ExitReason=exit_reason, Result=result, PnL=pnl)


# --------------------------------------------------------------------------- #
# paper trading
# --------------------------------------------------------------------------- #

async def paper_create(*, instrument_id: int, entry_time: datetime, entry_price: float,
                       quantity: int, signal_id: int | None = None,
                       stop_loss: float | None = None, target1: float | None = None,
                       target2: float | None = None) -> int | None:
    rows = await call_proc(
        "dbo.usp_PaperTrades_Create",
        SignalId=signal_id, InstrumentId=instrument_id, EntryTime=entry_time,
        EntryPrice=entry_price, Quantity=quantity, StopLossPrice=stop_loss,
        Target1Price=target1, Target2Price=target2)
    if not rows:
        return None
    for key in ("PaperTradeId", "papertradeid", "Id"):
        if key in rows[0]:
            return int(rows[0][key])
    val = list(rows[0].values())[0]
    return int(val) if val is not None else None


async def paper_close(*, paper_trade_id: int, exit_time: datetime, exit_price: float,
                      exit_reason: str, charges: float = 0.0) -> None:
    await call_proc(
        "dbo.usp_PaperTrades_Close",
        PaperTradeId=paper_trade_id, ExitTime=exit_time, ExitPrice=exit_price,
        ExitReason=exit_reason, Charges=charges)


async def paper_open() -> list[dict[str, Any]]:
    return await call_proc("dbo.usp_PaperTrades_GetOpen")


async def paper_history(*, from_time: datetime | None = None,
                        to_time: datetime | None = None) -> list[dict[str, Any]]:
    return await call_proc("dbo.usp_PaperTrades_GetHistory",
                           FromTime=from_time, ToTime=to_time)


async def paper_pnl_summary(*, from_time: datetime, to_time: datetime) -> dict[str, Any]:
    rows = await call_proc("dbo.usp_PaperTrades_GetPnLSummary",
                           FromTime=from_time, ToTime=to_time)
    return rows[0] if rows else {}


# --------------------------------------------------------------------------- #
# operations: feed health, logs, notifications
# --------------------------------------------------------------------------- #

async def feed_health_save(*, source: str, status: str, last_tick: datetime | None = None,
                           reconnects: int | None = None, response_ms: int | None = None,
                           token_status: str | None = None,
                           error: str | None = None) -> None:
    await call_proc(
        "dbo.usp_FeedHealth_Save",
        DataSource=source, ConnectionStatus=status, LastTickTime=last_tick,
        ReconnectCount=reconnects, ResponseTimeMs=response_ms,
        TokenRefreshStatus=token_status, ErrorMessage=error)


async def log_write(*, level: str, message: str, component: str | None = None,
                    exception: str | None = None, correlation_id: str | None = None) -> None:
    await call_proc(
        "dbo.usp_ApplicationLogs_Write",
        LogLevel=level, Component=component, Message=message,
        ExceptionDetails=exception, CorrelationId=correlation_id)


async def logs_get(*, from_time: datetime | None = None, to_time: datetime | None = None,
                   level: str | None = None, top: int = 100) -> list[dict[str, Any]]:
    return await call_proc("dbo.usp_ApplicationLogs_Get",
                           FromTime=from_time, ToTime=to_time, LogLevel=level, TopRows=top)


# Notifications reuse ApplicationLogs (your choice: no schema change). The payload is
# JSON in Message so the bell can render title/body, and CorrelationId carries SignalId
# which makes duplicate notifications for one signal detectable (AC-64).
NOTIFICATION_COMPONENT = "NOTIFICATION"


async def notification_write(*, kind: str, title: str, body: str,
                             signal_id: int | None = None) -> None:
    await log_write(
        level="INFO", component=NOTIFICATION_COMPONENT,
        message=json.dumps({"type": kind, "title": title, "body": body}),
        correlation_id=str(signal_id) if signal_id is not None else None)


async def notifications_get(*, top: int = 30) -> list[dict[str, Any]]:
    rows = await logs_get(level="INFO", top=max(top * 5, 100))
    out: list[dict[str, Any]] = []
    for r in rows:
        if (r.get("Component") or "") != NOTIFICATION_COMPONENT:
            continue
        try:
            payload = json.loads(r.get("Message") or "{}")
        except (TypeError, ValueError):
            payload = {"type": "INFO", "title": r.get("Message") or "", "body": ""}
        out.append({
            "id": str(r.get("LogId") or r.get("ApplicationLogId") or len(out)),
            "ts": r.get("LoggedAt") or r.get("CreatedAt"),
            "type": payload.get("type", "INFO"),
            "title": payload.get("title", ""),
            "body": payload.get("body", ""),
            "signal_id": r.get("CorrelationId"),
            "read": True,
        })
        if len(out) >= top:
            break
    return out


# --------------------------------------------------------------------------- #
# backtesting
# --------------------------------------------------------------------------- #
# Your original procedures accept a reduced parameter set (usp_BacktestRuns_Complete
# takes only @BacktestRunId and aggregates from BacktestTrades). The richer report the
# app produces needs migrations/001. Until that script is run, these functions fall
# back to the original procedures and report the shortfall through `capabilities()` —
# they never fabricate a column that does not exist.

async def backtest_create(*, run_key: str, start: date, end: date,
                          strategy_id: int | None = None,
                          strategy_version: str | None = None,
                          underlying: str | None = None, timeframe: str | None = None,
                          initial_capital: float | None = None,
                          risk_per_trade_pct: float | None = None,
                          assumptions: Any = None) -> int | None:
    if await proc_exists("dbo.usp_BacktestRuns_CreateV2"):
        rows = await call_proc(
            "dbo.usp_BacktestRuns_CreateV2",
            RunKey=run_key, StrategyId=strategy_id, StrategyVersion=strategy_version,
            UnderlyingSymbol=underlying, TimeFrame=timeframe, StartDate=start, EndDate=end,
            InitialCapital=initial_capital, RiskPerTradePct=risk_per_trade_pct,
            AssumptionsJson=_jsonify(assumptions), Status="QUEUED")
    else:
        logger.warning("usp_BacktestRuns_CreateV2 missing — run migrations/001 to persist "
                       "timeframe, symbol, risk%% and assumptions")
        rows = await call_proc(
            "dbo.usp_BacktestRuns_Create",
            StrategyId=strategy_id, StrategyVersion=strategy_version,
            StartDate=start, EndDate=end, InitialCapital=initial_capital)
    if not rows:
        return None
    for key in ("BacktestRunId", "backtestrunid", "Id"):
        if key in rows[0]:
            return int(rows[0][key])
    val = list(rows[0].values())[0]
    return int(val) if val is not None else None


async def backtest_set_status(*, run_id: int, status: str, error: str | None = None) -> None:
    """QUEUED -> RUNNING -> COMPLETED/FAILED (AC-83)."""
    if await proc_exists("dbo.usp_BacktestRuns_SetStatus"):
        await call_proc("dbo.usp_BacktestRuns_SetStatus",
                        BacktestRunId=run_id, Status=status, ErrorMessage=error)
    elif status in ("COMPLETED", "FAILED"):
        await call_proc("dbo.usp_BacktestRuns_Complete", BacktestRunId=run_id)


async def backtest_trade_insert(*, run_id: int, entry_time: datetime, entry_price: float,
                                quantity: int, trade_number: int | None = None,
                                instrument_id: int | None = None,
                                underlying: str | None = None,
                                trading_symbol: str | None = None,
                                expiry: date | None = None, strike: float | None = None,
                                option_type: str | None = None,
                                exit_time: datetime | None = None,
                                exit_price: float | None = None,
                                stop_loss: float | None = None,
                                target1: float | None = None, target2: float | None = None,
                                gross_pnl: float | None = None, charges: float | None = None,
                                pnl: float | None = None, r_multiple: float | None = None,
                                signal_score: float | None = None,
                                segment: str | None = None, regime: str | None = None,
                                exit_reason: str | None = None) -> None:
    if await proc_exists("dbo.usp_BacktestTrades_InsertV2"):
        await call_proc(
            "dbo.usp_BacktestTrades_InsertV2",
            BacktestRunId=run_id, TradeNumber=trade_number, InstrumentId=instrument_id,
            UnderlyingSymbol=underlying, TradingSymbol=trading_symbol, ExpiryDate=expiry,
            StrikePrice=strike, OptionType=option_type, EntryTime=entry_time,
            ExitTime=exit_time, EntryPrice=entry_price, ExitPrice=exit_price,
            Quantity=quantity, StopLossPrice=stop_loss, TargetPrice=target1,
            Target2Price=target2, GrossPnL=gross_pnl, Charges=charges, PnL=pnl,
            RMultiple=r_multiple, SignalScore=signal_score, Segment=segment,
            MarketRegime=regime, ExitReason=exit_reason)
    else:
        await call_proc(
            "dbo.usp_BacktestTrades_Insert",
            BacktestRunId=run_id, InstrumentId=instrument_id, EntryTime=entry_time,
            ExitTime=exit_time, EntryPrice=entry_price, ExitPrice=exit_price,
            Quantity=quantity, StopLossPrice=stop_loss, TargetPrice=target1,
            PnL=pnl, ExitReason=exit_reason)


async def backtest_complete(*, run_id: int, metrics: dict[str, Any],
                            equity_curve: Any = None) -> None:
    if await proc_exists("dbo.usp_BacktestRuns_CompleteV2"):
        await call_proc(
            "dbo.usp_BacktestRuns_CompleteV2",
            BacktestRunId=run_id,
            TotalTrades=metrics.get("total_trades", 0),
            WinningTrades=metrics.get("wins", 0),
            LosingTrades=metrics.get("losses", 0),
            WinRate=metrics.get("win_rate"),
            GrossPnL=metrics.get("gross_pnl"),
            TotalCosts=metrics.get("total_costs"),
            NetPnL=metrics.get("net_pnl"),
            ProfitFactor=metrics.get("profit_factor"),
            AvgWin=metrics.get("avg_win"),
            AvgLoss=metrics.get("avg_loss"),
            LargestWin=metrics.get("largest_win"),
            LargestLoss=metrics.get("largest_loss"),
            AvgRMultiple=metrics.get("avg_r"),
            MaxDrawdown=metrics.get("max_drawdown"),
            MaxDrawdownPct=metrics.get("max_drawdown_pct"),
            EquityCurveJson=_jsonify(equity_curve),
            MetricsJson=_jsonify(metrics),
            Status="COMPLETED")
    else:
        # the original proc derives the headline figures from BacktestTrades itself
        await call_proc("dbo.usp_BacktestRuns_Complete", BacktestRunId=run_id)


async def backtest_results(run_id: int) -> dict[str, Any]:
    rows = await call_proc("dbo.usp_BacktestRuns_GetResults", BacktestRunId=run_id)
    return rows[0] if rows else {}


async def backtest_list(*, top: int = 20) -> list[dict[str, Any]]:
    if await proc_exists("dbo.usp_BacktestRuns_GetList"):
        return await call_proc("dbo.usp_BacktestRuns_GetList", Top=top)
    return []


async def backtest_trades(run_id: int, *, top: int = 1000) -> list[dict[str, Any]]:
    if await proc_exists("dbo.usp_BacktestTrades_GetByRun"):
        return await call_proc("dbo.usp_BacktestTrades_GetByRun",
                               BacktestRunId=run_id, Top=top)
    return []
