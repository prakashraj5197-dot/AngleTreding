// Hand-written mirrors of the Pydantic models in backend/models/trading.py.
// Nothing infers across the HTTP boundary — change a model, change its interface here
// in the same edit.

export interface MarketStatus {
  status: string;
  ist_time: string;
  ist_date: string;
  session_elapsed: number;
  session_mode: string;
  simulated: boolean;
  note: string;
}

export interface Quote {
  symbol: string;
  name: string;
  ltp: number;
  open: number;
  high: number;
  low: number;
  prev_close: number;
  change: number;
  change_pct: number;
  volume: number;
  vwap: number;
  ts: string;
  market_status: string;
  session_elapsed: number;
  session_mode: string;
  simulated: boolean;
  regime: string;
}

export interface Candle {
  symbol: string;
  timeframe: string;
  ts: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  oi?: number | null;
}

export interface OptionRow {
  underlying: string;
  expiry: string;
  strike: number;
  option_type: string;
  ltp: number;
  bid: number;
  ask: number;
  volume: number;
  open_interest: number;
  change_in_oi: number;
  iv: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  moneyness: string;
  ts?: string | null;
}

export interface Chain {
  underlying: string;
  spot: number;
  atm_strike: number;
  ts: string;
  pcr: number;
  max_pain: number;
  futures_price: number;
  basis: number;
  fut_oi_change: number;
  regime: string;
  expiries: string[];
  rows: OptionRow[];
}

export interface Freshness {
  price_age_s: number | null;
  option_age_s: number | null;
  chain_age_s: number | null;
  price_ok: boolean;
  option_ok: boolean;
  chain_ok: boolean;
  forced_stale: boolean;
  stale: boolean;
}

export interface Health {
  app: string;
  database: string;
  provider: string;
  provider_mode: string;
  data_freshness: Freshness;
  last_signal_at: string | null;
  active_signals: number;
  server_time_utc: string;
}

export interface Factor {
  key: string;
  label: string;
  state: string;
  value: string;
  score: number;
  reason: string;
}

export interface Signal {
  id: string;
  created_at: string;
  updated_at: string | null;
  symbol: string;
  spot_at_signal: number;
  direction: string;
  option_type: string;
  strike: number;
  expiry: string;
  option_symbol: string;
  entry_min: number;
  entry_max: number;
  entry_price: number | null;
  stop_loss: number;
  target1: number;
  target2: number;
  risk_reward: number;
  risk_points: number;
  score: number;
  strength: string;
  status: string;
  result: string;
  exit_price: number | null;
  exit_time: string | null;
  pnl_points: number | null;
  option_ltp: number;
  max_qty: number;
  filled: boolean;
  paper_executed: boolean;
  strategy_name: string;
  strategy_version: string;
  day_ist: string;
  reasons: Factor[];
  no_trade_reason: string | null;
  snapshot: Record<string, unknown>;
  event_log: Array<{ ts: string; event: string; detail: string }>;
}

export interface EngineState {
  symbol: string;
  ts: string;
  market_status: string;
  stale: boolean;
  direction: string;
  score: number;
  display_score: number;
  signal_id: string | null;
  factors: Factor[];
  reasons: string[];
  no_trade_reason: string | null;
  indicators: Record<string, number | string | number[] | null>;
  evaluation_ms: number;
}

export interface Notification {
  id: string;
  ts: string;
  type: string;
  title: string;
  body: string;
  signal_id: string | null;
  read: boolean;
}

export interface PaperPosition {
  id: string;
  signal_id: string | null;
  symbol: string;
  option_symbol: string;
  option_type: string;
  strike: number;
  expiry: string;
  side: string;
  qty: number;
  entry_price: number;
  entry_time: string;
  stop_loss: number;
  target: number;
  exit_target: number;
  status: string;
  last_price: number;
  exit_price: number | null;
  exit_time: string | null;
  unrealized: number | null;
  realized_pnl: number | null;
  close_reason: string;
}

export interface PaperAccount {
  id: string;
  start_capital: number;
  cash: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  open_positions: number;
  peak_equity: number;
  drawdown: number;
  drawdown_pct: number;
  daily_pnl: number;
  trades_today: number;
  consecutive_losses: number;
  risk_blocked_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScannerRow extends OptionRow {
  spread_pct: number;
  score: number;
  score_breakdown: Record<string, number>;
  eligible: boolean;
  rejected: boolean;
  reject_reasons: string[];
  below_min_score: boolean;
  t_days: number;
}

export interface ScannerResult {
  underlying: string;
  spot: number;
  atm_strike: number;
  strike_step: number;
  expiry: string | null;
  expiries: string[];
  ts: string;
  pcr: number;
  max_pain: number;
  futures_price: number;
  basis: number;
  regime: string;
  market_status: string;
  thresholds: {
    min_oi: number;
    min_volume: number;
    max_spread_pct: number;
    min_premium: number;
    min_option_score: number;
    atm_range: number;
  };
  rows: ScannerRow[];
  top_ranked: ScannerRow[];
  recommended_ce: ScannerRow | null;
  recommended_pe: ScannerRow | null;
  eligible_count: number;
  rejected_count: number;
}

export interface BacktestMetrics {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  gross_pnl: number;
  total_costs: number;
  net_pnl: number;
  avg_profit: number;
  avg_loss: number;
  profit_factor: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  avg_r: number;
  largest_win: number;
  largest_loss: number;
  call_trades: number;
  put_trades: number;
  call_pnl: number;
  put_pnl: number;
  monthly: Array<{ month: string; trades: number; wins: number; pnl: number; win_rate: number }>;
  regime_stats: Array<{ regime: string; trades: number; wins: number; pnl: number; win_rate: number }>;
  segment_stats: Array<{ segment: string; trades: number; wins: number; pnl: number; win_rate: number }>;
}

export interface BacktestJob {
  id: string;
  status: string;
  params: Record<string, string | number | boolean | null>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: number;
  error: string | null;
  warnings: string[];
  dataset_info: Record<string, unknown>;
  metrics: BacktestMetrics | null;
  equity_curve: Array<{ t: string; equity: number }>;
  trades_count: number;
}

export interface BacktestTrade {
  n: number;
  entry_ts: string;
  exit_ts: string;
  side: string;
  strike: number;
  expiry: string;
  qty: number;
  entry_price: number;
  exit_price: number;
  sl: number;
  target: number;
  pnl: number;
  pnl_pct: number;
  r_multiple: number;
  result: string;
  exit_reason: string;
  regime: string;
  segment: string;
}

export interface DatasetEntry {
  symbol: string;
  timeframe: string;
  candles: number;
  from: string;
  to: string;
}

export interface SignalAnalytics {
  total_signals: number;
  closed: number;
  active: number;
  no_fill: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_r: number;
  profit_factor: number;
  total_points: number;
  max_drawdown_points: number;
  best_setup: { setup: string; trades: number; wins: number; pnl: number; win_rate: number } | null;
  worst_setup: { setup: string; trades: number; wins: number; pnl: number; win_rate: number } | null;
  setups: Array<{ setup: string; trades: number; wins: number; pnl: number; win_rate: number }>;
  equity_curve: Array<{ t: string; cum: number }>;
}

export interface StrategySettings {
  name: string;
  version: string;
  signal_timeframe: string;
  eval_interval_sec: number;
  min_signal_score: number;
  min_risk_reward: number;
  volume_multiplier: number;
  weights: { trend: number; vwap: number; momentum: number; breakout: number; volume: number; fno: number };
  ema_fast: number;
  ema_slow: number;
  rsi_period: number;
  atr_period: number;
  rsi_upper: number;
  rsi_lower: number;
  breakout_lookback: number;
  conflict_tolerance: number;
  signal_validity_min: number;
  cooldown_min: number;
  max_reentries_per_day: number;
  max_signals_per_symbol_day: number;
  max_signals_per_day: number;
  opening_filter_min: number;
  closing_filter_min: number;
  expiry_day_filter_min: number;
  sl_pct_of_premium: number;
  t1_rr: number;
  t2_rr: number;
  entry_range_pct: number;
}

export interface OptionSelectionSettings {
  atm_range: number;
  min_oi: number;
  min_volume: number;
  max_spread_pct: number;
  min_premium: number;
  min_option_score: number;
  weights: { liquidity: number; moneyness: number; oi_alignment: number; iv: number; spread: number };
}

export interface RiskSettings {
  capital: number;
  max_risk_per_trade: number;
  daily_loss_limit: number;
  consecutive_loss_limit: number;
  max_trades_per_day: number;
  enforce: boolean;
}

export interface DataSettings {
  provider: "simulated" | "angelone";
  session_mode: "always_on" | "market_hours";
  price_fresh_s: number;
  option_fresh_s: number;
  chain_fresh_s: number;
  force_stale: boolean;
  stale_block_signals: boolean;
  retention_candle_days: number;
  retention_option_snapshot_days: number;
}

export interface DbStatus {
  backend: string;
  label: string;
  connected: boolean;
  configured: boolean;
  missing_env: string[];
  host: string | null;
  database: string | null;
  driver_available: boolean;
  drivers: string[];
  tables: number | null;
  procedures: number | null;
  server_utc: string | null;
  detail: string;
  migration_001_applied: boolean | null;
  pending_migrations: string[];
}

export interface ProviderStatus {
  provider: string;
  label: string;
  connected: boolean;
  simulated: boolean;
  configured: boolean;
  missing_env: string[];
  last_login_ist: string | null;
  last_error: string | null;
  detail: string;
}

export interface ProviderTestResult {
  ok: boolean;
  message: string;
  client_code_masked: string | null;
  last_login_ist: string | null;
  missing_env: string[];
  option_contracts: Record<string, number>;
}

export interface AppSettings {
  strategy: StrategySettings;
  option_selection: OptionSelectionSettings;
  risk: RiskSettings;
  data: DataSettings;
  notifications: { enabled: boolean; channels: string[]; min_strength: number };
  paper: { start_capital: number; exit_target: number; slippage_pct: number; brokerage_per_order: number };
  updated_at: string | null;
}

export interface AuthState {
  ok: boolean;
  email: string | null;
}

export interface Instrument {
  symbol: string;
  name: string;
  kind: string;
  lot_size: number;
  strike_step: number;
}
