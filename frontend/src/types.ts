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
  use_donchian_compression: boolean;
  donchian_compression_lookback: number;
  donchian_compression_max_range_atr: number;
  use_donchian_rsi: boolean;
  /** Rolling mean length of ATR (intraday_donchian volatility filter). */
  atr_ma_period: number;
  /** Min distance past Donchian band in units of ATR. */
  breakout_atr_mult: number;
  /** 0 = off; LTF EMA for micro-trend alignment. */
  ltf_ema_period: number;
  /** Long if RSI < rsi_buy_max / short if RSI > rsi_sell_min when on. */
  use_breakout_rsi: boolean;
  /** Require current ATR > prior bar ATR. */
  use_atr_expansion: boolean;
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
  use_atr_max_filter: boolean;
  atr_max_pct: number;
  use_time_filter: boolean;
  /** Minutes from midnight UTC, start inclusive. */
  time_start_utc_mins: number;
  time_end_utc_mins: number;
  /** rsi_mean_reversion: only trade when ADX < this (0 = off). */
  mr_regime_adx_max: number;
  slippage_pct: number;
  slippage_atr_mult: number;
  half_spread_bps: number;
  intrabar_sl_tp_policy: string;
  intrabar_random_seed: number;
  enable_funding: boolean;
  funding_rate_bps: number;
  funding_interval_hours: number;
  use_trailing_stop: boolean;
  trailing_stop_pct: number;
  max_consecutive_losses: number;
  max_daily_loss_pct: number;
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
  funding_pnl?: number;
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
  skipped_by_circuit?: number;
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
  kind: "backtest" | "live" | "portfolio";
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

export interface ProfilesWalkforwardRebaselineStart {
  profiles?: string[];
  train_bars?: number;
  test_bars?: number;
  step?: number;
  mc_sims?: number;
  train_engine?: "grid" | "optuna";
  optuna_trials?: number;
  optuna_seed?: number;
  append_message?: string;
  dry_run?: boolean;
}

export interface ProfilesWalkforwardRebaselineResponse {
  ok: number;
  total: number;
  dry_run: boolean;
  elapsed_secs: number;
  profiles_updated: number;
  started_with: {
    train_bars: number;
    test_bars: number;
    step: number | null;
    mc_sims: number;
    train_engine: "grid" | "optuna" | string;
    optuna_trials: number;
    optuna_seed: number;
    profiles: string[];
  };
  rows: Array<{
    name: string;
    ok: boolean;
    error?: string;
    symbol?: string;
    timeframe?: string;
    strategy?: string;
    summary?: Record<string, unknown>;
  }>;
}

// ---- Walk-forward ----------------------------------------------------

export interface WalkforwardStart {
  params: Partial<StrategyParams>;
  train_bars: number;
  test_bars: number;
  step?: number;
  opt_matrix?: Record<string, (string | number | boolean)[]>;
  mc_sims?: number;
  /** `"grid"` = exhaustive Cartesian train search; `"optuna"` requires `optuna` Python package */
  train_engine?: "grid" | "optuna";
  /** Capped server-side at 512. */
  optuna_trials?: number;
  optuna_seed?: number;
}

export interface WalkforwardWindow {
  i: number;
  train_ret: number;
  test_ret: number;
  train_n: number;
  test_n: number;
  test_wr: number;
  test_mdd: number;
  train_score?: number;
  chosen?: Record<string, string | number | boolean>;
}

export interface WalkforwardTradeMonteCarlo {
  n_trades: number;
  sims: number;
  ret_mean_pct: number;
  ret_p05_pct: number;
  ret_p50_pct: number;
  ret_p95_pct: number;
  mdd_mean_pct: number;
  mdd_p95_pct: number;
}

export interface WalkforwardStabilityCell {
  x: string | number | boolean;
  y: string | number | boolean;
  n_windows: number;
  mean_test_ret: number;
  mean_test_mdd: number;
  mean_train_score: number;
  positive_rate: number;
}

export interface WalkforwardStabilityMatrix {
  x_key: string | null;
  y_key: string | null;
  cells: WalkforwardStabilityCell[];
}

export interface WalkforwardSummary {
  n_windows: number;
  mean_test_ret: number;
  median_test_ret: number;
  stdev_test_ret: number;
  mean_test_mdd_pct?: number;
  positive_rate: number;
  total_test_trades: number;
  total_train_trades: number;
  unique_selected_configs?: number;
  selection_transition_rate?: number;
  trade_mc?: WalkforwardTradeMonteCarlo;
  final_oos?: {
    start_bar: number;
    end_bar: number;
    bars: number;
    policy?: string;
    selected_windows?: number;
    selected_key?: [string, string | number | boolean][];
    chosen?: Record<string, string | number | boolean>;
    return_pct: number;
    trades: number;
    win_rate: number;
    max_drawdown_pct: number;
    profit_factor: number;
  };
  stability_matrix?: WalkforwardStabilityMatrix;
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
  n_candidates?: number;
  tuned_keys?: string[];
  mc_sims?: number;
  train_engine?: "grid" | "optuna";
  optuna_trials_requested?: number | null;
  optuna_trials_effective?: number | null;
  optuna_seed?: number | null;
  search_space_size?: number | null;
  dev_end_bar?: number | null;
  holdout_start_bar?: number | null;
  holdout_bars?: number | null;
}

export interface WalkforwardStabilityResponse {
  running: boolean;
  completed: number;
  total: number;
  n_candidates: number;
  tuned_keys: string[];
  train_engine?: "grid" | "optuna";
  optuna_trials_requested?: number | null;
  optuna_trials_effective?: number | null;
  optuna_seed?: number | null;
  search_space_size?: number | null;
  matrix: WalkforwardStabilityMatrix;
}

// ---- Regime engine ----------------------------------------------------
export interface RegimeExpectancyRow {
  strategy: string;
  regime: string;
  trades: number;
  win_rate: number;
  avg_pnl: number;
  expectancy_pct: number;
  total_pnl: number;
  return_pct: number;
}

export interface RegimeExpectancyResponse {
  symbol: string;
  timeframe: string;
  bars: number;
  strategies: string[];
  regimes: string[];
  rows: RegimeExpectancyRow[];
}

// ---- Portfolio runner -------------------------------------------------
export interface PortfolioRiskConfig {
  max_open_positions: number;
  max_correlated_positions: number;
  vol_target_atr_pct: number;
  vol_scale_min: number;
  vol_scale_max: number;
  circuit_ema_fast: number;
  circuit_ema_slow: number;
  circuit_sigma: number;
  max_positions_per_group: number;
  risk_budget_overrides: Record<string, number>;
  correlation_groups: Record<string, string>;
}

export interface PortfolioRunResponse {
  result: {
    method: string;
    symbol: string;
    timeframe: string;
    bars: number;
    master_initial_balance: number;
    weights: Record<string, number>;
    risk_budget_weights: Record<string, number>;
    risk_scales: Record<string, number>;
    risk_config: PortfolioRiskConfig;
    combined: {
      balance: number;
      total_pnl: number;
      return_pct: number;
      total_trades: number;
      max_drawdown_pct: number;
      max_drawdown_pct_conservative_proxy: number;
      skipped_by_risk_limit: number;
      skipped_by_corr_limit: number;
      skipped_by_group_limit: number;
      skipped_by_circuit: number;
      circuit_halted_bars: number;
    };
    sleeves: Array<{
      strategy: string;
      weight: number;
      allocation: number;
      summary: Partial<BacktestSummary>;
    }>;
  };
  saved?: RunMeta | null;
}

// ---- Automation / monitoring -----------------------------------------
export interface TournamentRow {
  name: string;
  ok: boolean;
  deployment_status?: "promoted" | "candidate" | "demoted" | string;
  tournament_score?: number;
  error?: string;
}

export interface TournamentRunResponse {
  ok: number;
  total: number;
  promoted: number;
  demoted: number;
  candidate: number;
  rows: TournamentRow[];
  requested_engine?: "grid" | "optuna" | string;
  effective_engine?: "grid" | "optuna" | string;
  fallback_reason?: string | null;
}

export interface DivergenceResponse {
  symbol: string;
  timeframe: string;
  bars: number;
  live_trades: number;
  backtest_trades: number;
  matched_trades: number;
  unmatched_live_trades: number;
  unmatched_backtest_trades: number;
  trade_count_delta: number;
  live_return_pct: number;
  backtest_return_pct: number;
  return_delta_pct: number;
  live_win_rate: number;
  backtest_win_rate: number;
  timestamp_match_rate: number;
  mean_abs_entry_slip_pct: number;
  mean_abs_exit_slip_pct: number;
  mean_abs_pnl_delta_pct: number;
  thresholds: Record<string, number>;
  verdict: "aligned" | "diverged";
}

export interface ReadinessResponse {
  days: number;
  runs_considered: number;
  summary: {
    samples: number;
    aligned: number;
    aligned_pct: number;
    avg_timestamp_match_rate: number;
    avg_mean_abs_pnl_delta_pct: number;
    min_aligned_pct: number;
    min_samples: number;
    min_avg_timestamp_match_rate: number;
    max_avg_mean_abs_pnl_delta_pct: number;
    verdict: "READY" | "NOT_READY" | "NO_DATA";
  };
  rows: Array<{
    run_id: string;
    label: string;
    created_at: string;
    verdict: "aligned" | "diverged" | string;
    return_delta_pct: number;
    trade_count_delta: number;
    timestamp_match_rate: number;
    mean_abs_pnl_delta_pct: number;
  }>;
}
