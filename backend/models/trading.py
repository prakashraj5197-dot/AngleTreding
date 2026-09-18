"""Pydantic v2 models for API request/response bodies.

Every model here has a hand-written TS mirror in frontend/src/lib/types.ts — keep the
pair in sync in the same edit (see TEMPLATE.md §4). Timestamps are UTC-aware; the UI
renders them in IST.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- market data


class Candle(BaseModel):
    symbol: str
    timeframe: str  # 1m | 5m | 15m
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    v: float
    oi: float | None = None


class MarketStatusOut(BaseModel):
    status: str  # OPEN | CLOSED
    ist_time: str
    ist_date: str
    session_elapsed: int
    session_mode: str
    simulated: bool
    note: str = ""


class QuoteOut(BaseModel):
    symbol: str
    name: str
    ltp: float
    open: float
    high: float
    low: float
    prev_close: float
    change: float
    change_pct: float
    volume: float
    vwap: float
    ts: datetime
    market_status: str
    session_elapsed: int
    session_mode: str
    simulated: bool
    regime: str


class OptionRowOut(BaseModel):
    underlying: str
    expiry: str
    strike: float
    option_type: str  # CE | PE
    ltp: float
    bid: float
    ask: float
    volume: int
    open_interest: int
    change_in_oi: int
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float
    moneyness: str = ""
    ts: datetime | None = None


class ChainOut(BaseModel):
    underlying: str
    spot: float
    atm_strike: float
    ts: datetime
    pcr: float
    max_pain: float
    futures_price: float
    basis: float
    fut_oi_change: int
    regime: str
    expiries: list[str] = []
    rows: list[OptionRowOut]


class FreshnessOut(BaseModel):
    price_age_s: float | None = None
    option_age_s: float | None = None
    chain_age_s: float | None = None
    price_ok: bool = False
    option_ok: bool = False
    chain_ok: bool = False
    forced_stale: bool = False
    stale: bool = False


class HealthOut(BaseModel):
    app: str  # ok | degraded
    database: str
    provider: str
    provider_mode: str
    data_freshness: FreshnessOut
    last_signal_at: datetime | None = None
    active_signals: int = 0
    server_time_utc: datetime


# ---------------------------------------------------------------- signals


class FactorOut(BaseModel):
    key: str
    label: str
    state: str  # bull | bear | neutral
    value: str
    score: float
    reason: str


class Signal(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime | None = None
    symbol: str
    spot_at_signal: float
    direction: str  # BULLISH | BEARISH
    option_type: str  # CE | PE
    strike: float
    expiry: str
    option_symbol: str
    entry_min: float
    entry_max: float
    entry_price: float | None = None
    stop_loss: float
    target1: float
    target2: float
    risk_reward: float
    risk_points: float
    score: float
    strength: str
    status: str  # ACTIVE | TARGET1_HIT | TARGET2_HIT | STOP_LOSS | EXPIRED | MISSED_ENTRY | CANCELLED | DATA_ERROR
    result: str  # OPEN | WIN | LOSS | FLAT
    exit_price: float | None = None
    exit_time: datetime | None = None
    pnl_points: float | None = None
    option_ltp: float
    max_qty: int = 0
    filled: bool = False
    paper_executed: bool = False
    strategy_name: str
    strategy_version: str
    day_ist: str = ""
    reasons: list[FactorOut] = []
    no_trade_reason: str | None = None
    snapshot: dict[str, Any] = {}
    event_log: list[dict[str, Any]] = []


class EngineState(BaseModel):
    symbol: str
    ts: datetime
    market_status: str
    stale: bool
    direction: str  # BULLISH | BEARISH | SIDEWAYS | NO_TRADE
    score: float
    display_score: int
    signal_id: str | None = None
    factors: list[FactorOut] = []
    reasons: list[str] = []
    no_trade_reason: str | None = None
    indicators: dict[str, Any] = {}
    evaluation_ms: int = 0


class NotificationOut(BaseModel):
    id: str
    ts: datetime
    type: str  # NEW_SIGNAL | TARGET1 | TARGET2 | STOP_LOSS | EXPIRED | MISSED_ENTRY | RISK | PAPER | SYSTEM
    title: str
    body: str
    signal_id: str | None = None
    read: bool = False


# ---------------------------------------------------------------- paper trading


class PaperPosition(BaseModel):
    id: str
    signal_id: str | None = None
    symbol: str
    option_symbol: str
    option_type: str
    strike: float
    expiry: str
    side: str = "BUY"
    qty: int
    entry_price: float
    entry_time: datetime
    stop_loss: float
    target: float
    exit_target: int = 1
    status: str  # OPEN | CLOSED
    last_price: float
    exit_price: float | None = None
    exit_time: datetime | None = None
    unrealized: float | None = None
    realized_pnl: float | None = None
    close_reason: str = ""


class PaperAccount(BaseModel):
    id: str
    start_capital: float
    cash: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    open_positions: int
    peak_equity: float
    drawdown: float
    drawdown_pct: float
    daily_pnl: float
    trades_today: int
    consecutive_losses: int
    risk_blocked_reason: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- backtesting


class BacktestTradeOut(BaseModel):
    n: int
    entry_ts: datetime
    exit_ts: datetime
    side: str  # CE | PE
    strike: float
    expiry: str
    qty: int
    entry_price: float
    exit_price: float
    sl: float
    target: float
    pnl: float
    pnl_pct: float
    r_multiple: float
    result: str  # WIN | LOSS | FLAT
    exit_reason: str
    regime: str
    segment: str  # development | validation | out_of_sample


class BacktestMetrics(BaseModel):
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    gross_pnl: float = 0.0
    total_costs: float = 0.0
    net_pnl: float = 0.0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_r: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    call_trades: int = 0
    put_trades: int = 0
    call_pnl: float = 0.0
    put_pnl: float = 0.0
    monthly: list[dict[str, Any]] = []
    regime_stats: list[dict[str, Any]] = []
    segment_stats: list[dict[str, Any]] = []


class BacktestJobOut(BaseModel):
    id: str
    status: str  # QUEUED | RUNNING | COMPLETED | FAILED
    params: dict[str, Any]
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: float = 0.0
    error: str | None = None
    warnings: list[str] = []
    dataset_info: dict[str, Any] = {}
    metrics: BacktestMetrics | None = None
    equity_curve: list[dict[str, Any]] = []
    trades_count: int = 0


class BacktestRunRequest(BaseModel):
    symbol: str = "NIFTY"
    from_date: str
    to_date: str
    timeframe: Literal["1m", "5m", "15m"] = "5m"
    strategy: str = "QuantPulse Momentum"
    initial_capital: float = 500000.0
    risk_per_trade_pct: float = 1.0
    daily_loss_limit_pct: float = 2.0
    slippage_pct: float = 0.10
    brokerage_per_order: float = 20.0
    charges_pct: float = 0.05
    min_signal_score: float | None = None
    min_risk_reward: float | None = None
    conservative_same_candle_rule: bool = True


# ---------------------------------------------------------------- settings


class StrategyWeights(BaseModel):
    trend: float = 20
    vwap: float = 15
    momentum: float = 15
    breakout: float = 20
    volume: float = 15
    fno: float = 15


class OptionScoreWeights(BaseModel):
    liquidity: float = 30
    moneyness: float = 25
    oi_alignment: float = 20
    iv: float = 15
    spread: float = 10


class StrategySettings(BaseModel):
    name: str = "QuantPulse Momentum"
    version: str = "1.0.0"
    signal_timeframe: Literal["5m"] = "5m"
    eval_interval_sec: int = 60
    min_signal_score: float = 50
    min_risk_reward: float = 1.5
    volume_multiplier: float = 1.5
    weights: StrategyWeights = Field(default_factory=StrategyWeights)
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    atr_period: int = 14
    rsi_upper: float = 78
    rsi_lower: float = 22
    breakout_lookback: int = 20
    conflict_tolerance: float = 20
    signal_validity_min: int = 30
    cooldown_min: int = 15
    max_reentries_per_day: int = 1
    max_signals_per_symbol_day: int = 5
    max_signals_per_day: int = 10
    opening_filter_min: int = 5
    closing_filter_min: int = 15
    expiry_day_filter_min: int = 30
    sl_pct_of_premium: float = 22
    t1_rr: float = 1.6
    t2_rr: float = 2.4
    entry_range_pct: float = 1.0


class OptionSelectionSettings(BaseModel):
    atm_range: int = 10
    min_oi: int = 10000
    min_volume: int = 5000
    max_spread_pct: float = 2.0
    min_premium: float = 20
    min_option_score: float = 60
    weights: OptionScoreWeights = Field(default_factory=OptionScoreWeights)


class RiskSettings(BaseModel):
    """Spec §36.24-26 keeps the *percentages* (1% risk/trade, 2% daily loss, 3 consecutive
    losses) but its ₹11,000 illustration cannot fund a single NIFTY lot: 75 × ~₹6.5 of
    premium risk ≈ ₹490 per lot, so a ₹110 cap always rounds to zero quantity. Capital is
    therefore defaulted to ₹5,00,000 with the same 1% / 2% ratios intact, and every value
    stays user-configurable on the Settings page."""

    capital: float = 500000
    max_risk_per_trade: float = 5000
    daily_loss_limit: float = 10000
    consecutive_loss_limit: int = 3
    max_trades_per_day: int = 10
    enforce: bool = True


class DataSettings(BaseModel):
    provider: Literal["simulated", "angelone"] = "simulated"
    session_mode: Literal["always_on", "market_hours"] = "always_on"
    price_fresh_s: int = 3
    option_fresh_s: int = 5
    chain_fresh_s: int = 15
    force_stale: bool = False
    stale_block_signals: bool = True
    retention_candle_days: int = 730
    retention_option_snapshot_days: int = 30


class NotificationSettings(BaseModel):
    enabled: bool = True
    channels: list[str] = ["web"]
    min_strength: float = 70


class PaperSettings(BaseModel):
    start_capital: float = 500000
    exit_target: Literal[1, 2] = 1
    slippage_pct: float = 0.10
    brokerage_per_order: float = 20


class AppSettings(BaseModel):
    strategy: StrategySettings = Field(default_factory=StrategySettings)
    option_selection: OptionSelectionSettings = Field(default_factory=OptionSelectionSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    paper: PaperSettings = Field(default_factory=PaperSettings)
    updated_at: datetime | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class ProviderStatusOut(BaseModel):
    provider: str
    label: str
    connected: bool
    simulated: bool
    configured: bool
    missing_env: list[str] = []
    last_login_ist: str | None = None
    last_error: str | None = None
    detail: str = ""


class ProviderTestOut(BaseModel):
    ok: bool
    message: str
    client_code_masked: str | None = None
    last_login_ist: str | None = None
    missing_env: list[str] = []
    option_contracts: dict[str, int] = {}


class TokenOut(BaseModel):
    ok: bool
    email: str | None = None


class EvaluateRequest(BaseModel):
    symbol: str | None = None
