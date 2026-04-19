export type TradeReason =
  | "signal"
  | "reverse"
  | "stop_loss"
  | "take_profit"
  | "backtest_end"
  | string;

export interface Trade {
  timestamp?: string;
  opened_at?: string;
  side?: "LONG" | "SHORT";
  entry: number;
  exit: number;
  size?: number;
  gross_profit?: number;
  fee?: number;
  profit: number; // net of fees
  reason?: TradeReason;
}

export interface EquityPoint {
  timestamp: string;
  balance: number;
  /** True at trade closes / origin, false for mark-to-market ticks. */
  realized?: boolean;
}

export interface DashboardData {
  initial_balance: number;
  balance: number;
  position: "LONG" | "SHORT" | null;
  entry_price: number;
  position_size?: number;
  stop_price?: number;
  take_price?: number;
  trades: Trade[];
  equity_history: EquityPoint[];
  updated_at: string | null;
  config?: {
    allocation_pct: number;
    stop_loss_pct: number;
    take_profit_pct: number;
  };
  error?: string;
}

export type DataSource = "live" | "backtest";

/** Full Params payload sent to /backtest/run and /live/start. */
export interface StrategyParams {
  symbol: string;
  timeframe: string;
  bars: number;
  strategy: string;
  ema_short: number;
  ema_long: number;
  ema_trend: number;
  rsi_period: number;
  rsi_buy_max: number;
  rsi_sell_min: number;
  rsi_oversold: number;
  rsi_overbought: number;
  donchian_period: number;
  initial_balance: number;
  allocation_pct: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  entry_cooldown_bars: number;
  fee_pct: number;
  // ATR-based sizing (optional volatility-scaled risk)
  use_atr_sizing: boolean;
  atr_period: number;
  atr_risk_pct: number;
  atr_stop_mult: number;
  atr_tp_mult: number;
  // Generic filters — each one is an independent opt-in gate applied on
  // top of every strategy's signal. See strategies.filters_pass in the
  // backend for the evaluation logic.
  use_htf_confirm: boolean;
  htf_timeframe: string;
  htf_ema_period: number;
  use_adx_filter: boolean;
  filter_adx_period: number;
  adx_min: number;
  adx_max: number;
  use_volume_filter: boolean;
  vol_ma_period: number;
  vol_mult: number;
  use_atr_filter: boolean;
  atr_min_pct: number;
  use_macd_confirm: boolean;
  macd_fast: number;
  macd_slow: number;
  macd_signal: number;
}

export interface StrategyInfo {
  name: string;
  /** Params field names the strategy actually reads. */
  hyperparams: (keyof StrategyParams)[];
}

export interface BacktestSummary {
  trades: number;
  wins?: number;
  losses?: number;
  win_rate?: number;
  gross_pnl?: number;
  fees_paid?: number;
  total_pnl?: number;
  balance: number;
  return_pct: number;
  /** sum(wins) / |sum(losses)|, clamped to 999 when no losses. */
  profit_factor?: number;
  /** mean(trade_return) / stdev(trade_return). Not annualised. */
  trade_sharpe?: number;
  /** Peak-to-trough % drawdown of the MTM equity curve. */
  max_drawdown_pct?: number;
  avg_trade_pnl?: number;
  reasons?: Record<string, number>;
  skipped_by_cooldown?: number;
  timeframe?: string;
  bars?: number;
}

/** Payload sent to POST /sweep/start. */
export interface SweepStart {
  base_params: Partial<StrategyParams>;
  matrix: Record<string, (string | number | boolean)[]>;
  label_prefix?: string;
}

export interface SweepStatus {
  running: boolean;
  total: number;
  completed: number;
  current: Record<string, string | number | boolean> | null;
  results: RunMeta[];
  error: string | null;
  started_at: number | null;
  finished_at: number | null;
  label_prefix: string | null;
}

export interface RunMeta {
  id: string;
  label: string;
  kind: "backtest" | "live";
  created_at: string;
  params: StrategyParams;
  summary: Partial<BacktestSummary> & {
    trades: number;
    balance: number;
    return_pct: number;
  };
}

export interface RunPayload {
  meta: RunMeta;
  data: DashboardData;
}

export interface BacktestRunResponse {
  summary: BacktestSummary;
  data: DashboardData;
  saved: RunMeta | null;
}

export interface LiveStatus {
  running: boolean;
  started_at: number | null;
  last_tick_at: number | null;
  last_signal: string;
  last_price: number | null;
  last_error: string | null;
  params: StrategyParams | null;
  balance: number | null;
  position: "LONG" | "SHORT" | null;
  saved?: RunMeta | null;
}

// ---- Profiles --------------------------------------------------------
// Per-market parameter presets persisted on the backend. See profiles.py
// for the disk layout (profiles/*.json) and the auto-minimisation
// behaviour: save only stores fields that differ from config.py
// defaults, so a profile's params dict is typically sparse.

/** Performance baseline attached to a profile at save time. Only the
 *  summary is persisted (summary_only scope chosen at design time).
 *  The summary intentionally typed as a plain record so arbitrary
 *  future metrics round-trip without frontend changes. */
export interface ProfilePerformance {
  kind?: "backtest" | "walkforward" | string;
  run_id?: string;
  recorded_at?: string;
  summary?: Record<string, unknown>;
}

/** Single user-authored changelog entry. Message is required; `at` is
 *  server-stamped on save / PATCH. */
export interface ProfileChangelogEntry {
  at: string;
  message: string;
}

/** Performance preview shown on the Profiles list view. Slimmer than
 *  the full `ProfilePerformance.summary` — just the metrics the list
 *  column needs to render without the detail pane open. */
export interface ProfilePerformancePreview {
  kind?: string;
  trades?: number;
  return_pct?: number;
  max_drawdown_pct?: number;
  profit_factor?: number;
  trade_sharpe?: number;
  win_rate?: number;
}

/** Lightweight meta returned from GET /profiles (for dropdowns + list). */
export interface ProfileMeta {
  name: string;
  description: string;
  source: string;
  parent: string | null;
  created_at: string | null;
  /** Shallow view of the identifying fields (may be empty if all
   *  match defaults). */
  preview: Partial<Pick<StrategyParams, "symbol" | "timeframe" | "strategy">>;
  /** How many Params fields this profile overrides. */
  override_count: number;
  /** Number of profiles whose `parent` is this name. */
  version_count: number;
  performance_preview: ProfilePerformancePreview | null;
}

/** Full document returned from GET /profiles/<name>. */
export interface ProfileDoc {
  name: string;
  description: string;
  source: string;
  parent: string | null;
  created_at: string | null;
  changelog: ProfileChangelogEntry[];
  performance: ProfilePerformance | null;
  /** Sparse override set — fields not present inherit from config.py. */
  params: Partial<StrategyParams>;
}

/** Payload for POST /profiles. */
export interface SaveProfilePayload {
  name: string;
  params: Partial<StrategyParams>;
  description?: string;
  source?: string;
  parent?: string | null;
  changelog_message?: string;
  performance?: ProfilePerformance | null;
}

/** Payload for PATCH /profiles/<name>. All fields optional; omitted
 *  means "leave alone". `clear_performance: true` is the only way to
 *  explicitly drop the baseline. */
export interface UpdateProfilePayload {
  description?: string;
  source?: string;
  append_message?: string;
  performance?: ProfilePerformance | null;
  clear_performance?: boolean;
}

// ---- Walk-forward ----------------------------------------------------

export interface WalkforwardStart {
  params: Partial<StrategyParams>;
  train_bars: number;
  test_bars: number;
  step?: number;
}

export interface WalkforwardWindow {
  i: number;
  train_ret: number;
  test_ret: number;
  train_n: number;
  test_n: number;
  test_wr: number;
  test_mdd: number;
}

export interface WalkforwardSummary {
  n_windows: number;
  mean_test_ret: number;
  median_test_ret: number;
  stdev_test_ret: number;
  positive_rate: number;
  total_test_trades: number;
  total_train_trades: number;
  /** Heuristic rollup — see walkforward_runner._aggregate. */
  verdict: "ROBUST" | "WEAK" | "NOT_VIABLE" | "NO_DATA";
}

export interface WalkforwardStatus {
  running: boolean;
  total: number;
  completed: number;
  current: { i: number; of: number } | null;
  windows: WalkforwardWindow[];
  summary: WalkforwardSummary | null;
  error: string | null;
  started_at: number | null;
  finished_at: number | null;
  train_bars: number;
  test_bars: number;
  step: number;
  total_bars: number;
  params: {
    strategy?: string;
    symbol?: string;
    timeframe?: string;
    bars?: number;
  };
}
