import { clsx } from "clsx";
import { useMemo } from "react";
import type { StrategyInfo, StrategyParams } from "../types";

/** Fields that are always editable, grouped by section for the UI. */
const MARKET_FIELDS: (keyof StrategyParams)[] = ["symbol", "timeframe", "bars"];

const RISK_FIELDS: (keyof StrategyParams)[] = [
  "initial_balance",
  "allocation_pct",
  "stop_loss_pct",
  "take_profit_pct",
  "entry_cooldown_bars",
  "fee_pct",
  "slippage_pct",
  "slippage_atr_mult",
  "half_spread_bps",
  "intrabar_sl_tp_policy",
  "intrabar_random_seed",
  "enable_funding",
  "funding_rate_bps",
  "funding_interval_hours",
  "use_trailing_stop",
  "trailing_stop_pct",
  "max_consecutive_losses",
  "max_daily_loss_pct",
];

const ATR_FIELDS: (keyof StrategyParams)[] = [
  "atr_period",
  "atr_risk_pct",
  "atr_stop_mult",
  "atr_tp_mult",
];

/**
 * Generic filter groups. Each group is a single toggle plus the sub-knobs
 * that only matter when the toggle is on. Order here controls the UI order
 * inside the "Filters" section. Keep it aligned with backend defaults in
 * config.py and the FILTER_HYPERPARAMS list in strategies.py — the toggles
 * listed here are what the user can flip from the dashboard.
 */
const FILTER_GROUPS: {
  toggle: keyof StrategyParams;
  label: string;
  help: string;
  fields: (keyof StrategyParams)[];
}[] = [
  {
    toggle: "use_htf_confirm",
    label: "Higher-timeframe trend confirmation",
    help: "Only take longs when the higher-TF EMA is rising (shorts when falling).",
    fields: ["htf_timeframe", "htf_ema_period"],
  },
  {
    toggle: "use_adx_filter",
    label: "ADX regime filter",
    help: "adx_min > 0 requires trending market, adx_max > 0 requires ranging.",
    fields: ["filter_adx_period", "adx_min", "adx_max"],
  },
  {
    toggle: "use_volume_filter",
    label: "Volume filter",
    help: "Require signal-bar volume > vol_mult × rolling median.",
    fields: ["vol_ma_period", "vol_mult"],
  },
  {
    toggle: "use_atr_filter",
    label: "Minimum volatility (ATR %)",
    help: "Skip signals when ATR / price is below atr_min_pct.",
    fields: ["atr_min_pct"],
  },
  {
    toggle: "use_atr_max_filter",
    label: "Maximum volatility (ATR %)",
    help: "Skip signals when ATR / price exceeds atr_max (spike / news guard).",
    fields: ["atr_max_pct"],
  },
  {
    toggle: "use_time_filter",
    label: "Time of day (UTC)",
    help: "Only take signals when bar time falls in [start, end) minutes from midnight.",
    fields: ["time_start_utc_mins", "time_end_utc_mins"],
  },
  {
    toggle: "use_macd_confirm",
    label: "MACD confirmation",
    help: "Require MACD line on trade side (> signal & > 0 for longs).",
    fields: ["macd_fast", "macd_slow", "macd_signal"],
  },
];

/**
 * Fields owned by the Filters section — excluded from the generic
 * "Strategy parameters" grid so we don't render them twice (strategies.py
 * appends these to every strategy's hyperparams list).
 */
const FILTER_FIELD_KEYS = new Set<keyof StrategyParams>(
  FILTER_GROUPS.flatMap((g) => [g.toggle, ...g.fields])
);

const FIELD_META: Record<
  keyof StrategyParams,
  {
    label: string;
    type: "number" | "text" | "select" | "boolean";
    step?: number;
    min?: number;
    max?: number;
    help?: string;
    options?: string[];
  }
> = {
  // market
  symbol: { label: "Symbol", type: "text", help: "e.g. BTC/USDT" },
  timeframe: {
    label: "Timeframe",
    type: "select",
    options: ["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"],
  },
  bars: { label: "Bars (history)", type: "number", step: 100, min: 100 },
  // strategy-specific
  strategy: { label: "Strategy", type: "text" }, // handled separately
  ema_short: { label: "EMA short", type: "number", step: 1, min: 2 },
  ema_long: { label: "EMA long", type: "number", step: 1, min: 2 },
  ema_trend: {
    label: "EMA trend filter",
    type: "number",
    step: 1,
    min: 0,
    help: "0 = disabled",
  },
  rsi_period: { label: "RSI period", type: "number", step: 1, min: 2 },
  rsi_buy_max: {
    label: "RSI buy max",
    type: "number",
    step: 1,
    min: 0,
    max: 100,
    help: "skip long if RSI ≥ this",
  },
  rsi_sell_min: {
    label: "RSI sell min",
    type: "number",
    step: 1,
    min: 0,
    max: 100,
    help: "skip short if RSI ≤ this",
  },
  rsi_oversold: {
    label: "RSI oversold",
    type: "number",
    step: 1,
    min: 0,
    max: 100,
  },
  rsi_overbought: {
    label: "RSI overbought",
    type: "number",
    step: 1,
    min: 0,
    max: 100,
  },
  donchian_period: {
    label: "Donchian lookback",
    type: "number",
    step: 1,
    min: 2,
  },
  use_donchian_compression: {
    label: "Compression gate (Donchian)",
    type: "boolean",
    help: "Require prior mean range ≤ k×ATR before a valid break",
  },
  donchian_compression_lookback: {
    label: "Compression lookback",
    type: "number",
    step: 1,
    min: 1,
    help: "Bars for mean(high−low) before the signal bar",
  },
  donchian_compression_max_range_atr: {
    label: "Max range / ATR",
    type: "number",
    step: 0.1,
    min: 0,
    help: "Allow break only if prior mean range ≤ this × ATR",
  },
  use_donchian_rsi: {
    label: "RSI anti-chase (Donchian)",
    type: "boolean",
    help: "Long only if RSI < buy max; short only if RSI > sell min",
  },
  atr_ma_period: {
    label: "ATR mean period",
    type: "number",
    step: 1,
    min: 1,
    help: "require ATR above this rolling mean (volatility alive)",
  },
  breakout_atr_mult: {
    label: "Min breakout × ATR",
    type: "number",
    step: 0.05,
    min: 0,
    help: "extension past Donchian band ≥ this × ATR",
  },
  ltf_ema_period: {
    label: "LTF micro EMA",
    type: "number",
    step: 1,
    min: 0,
    help: "0 = off; long above / short below this EMA",
  },
  use_breakout_rsi: {
    label: "RSI breakout filter",
    type: "boolean",
    help: "long only if RSI < buy max; short only if RSI > sell min",
  },
  use_atr_expansion: {
    label: "ATR expansion",
    type: "boolean",
    help: "require ATR > prior bar",
  },
  // risk
  initial_balance: {
    label: "Initial balance",
    type: "number",
    step: 100,
    min: 0,
  },
  allocation_pct: {
    label: "Allocation",
    type: "number",
    step: 0.05,
    min: 0,
    max: 1,
    help: "fraction of balance per trade (0–1)",
  },
  stop_loss_pct: {
    label: "Stop loss",
    type: "number",
    step: 0.005,
    min: 0,
    help: "0.02 = 2%",
  },
  take_profit_pct: {
    label: "Take profit",
    type: "number",
    step: 0.005,
    min: 0,
    help: "0.04 = 4%",
  },
  entry_cooldown_bars: {
    label: "Entry cooldown",
    type: "number",
    step: 1,
    min: 0,
    help: "bars to wait after a close",
  },
  fee_pct: {
    label: "Fee (per-side)",
    type: "number",
    step: 0.0001,
    min: 0,
    help: "0.001 = 0.1%",
  },
  slippage_pct: {
    label: "Slippage (per side)",
    type: "number",
    step: 0.0001,
    min: 0,
    help: "Proportional adverse fill; 0.0005 = 0.05% per fill",
  },
  slippage_atr_mult: {
    label: "ATR × slippage",
    type: "number",
    step: 0.05,
    min: 0,
    help:
      "Added slippage = this × ATR/price each fill (0 = off); uses atr_period",
  },
  half_spread_bps: {
    label: "Half-spread (bps)",
    type: "number",
    step: 1,
    min: 0,
    help:
      "Fixed liquidity cost per fill: adds bps÷10000 to fractional slip (distinct from pct + ATR terms)",
  },
  intrabar_sl_tp_policy: {
    label: "Same-bar SL vs TP",
    type: "select",
    options: ["stop_first", "take_first", "random"],
    help:
      "If both brackets touch one candle: conservative stop-first, optimistic take-first, or coin flip",
  },
  intrabar_random_seed: {
    label: "Intrabar random seed",
    type: "number",
    step: 1,
    help:
      "When policy is random: fixed seed ⇒ reproducible coin flips across runs.",
  },
  enable_funding: {
    label: "Enable funding",
    type: "boolean",
    help:
      "Perpetual-style periodic funding transfer while position remains open.",
  },
  funding_rate_bps: {
    label: "Funding rate (bps)",
    type: "number",
    step: 0.1,
    help:
      "Per funding interval. Positive means longs pay shorts; negative reverses.",
  },
  funding_interval_hours: {
    label: "Funding interval (hours)",
    type: "number",
    step: 1,
    min: 1,
    help: "Settlement cadence for funding accrual.",
  },
  use_trailing_stop: { label: "Trailing stop", type: "boolean" },
  trailing_stop_pct: {
    label: "Trail distance",
    type: "number",
    step: 0.002,
    min: 0,
    help: "Stop trails this far from best price since entry (0.015 = 1.5%)",
  },
  max_consecutive_losses: {
    label: "Max consecutive losses",
    type: "number",
    step: 1,
    min: 0,
    help: "0 = off; halts new entries after N losing trades in a row",
  },
  max_daily_loss_pct: {
    label: "Max daily loss (UTC)",
    type: "number",
    step: 0.02,
    min: 0,
    help: "0 = off; halt new entries if realized balance drops this % from day start",
  },
  // ATR sizing
  use_atr_sizing: { label: "ATR sizing", type: "text" }, // rendered as toggle
  atr_period: {
    label: "ATR period",
    type: "number",
    step: 1,
    min: 2,
    help: "Wilder smoothing window",
  },
  atr_risk_pct: {
    label: "Risk per trade",
    type: "number",
    step: 0.0025,
    min: 0,
    max: 0.25,
    help: "0.01 = 1% of balance",
  },
  atr_stop_mult: {
    label: "Stop × ATR",
    type: "number",
    step: 0.1,
    min: 0.1,
    help: "SL = entry ± this × ATR",
  },
  atr_tp_mult: {
    label: "Take × ATR",
    type: "number",
    step: 0.1,
    min: 0.1,
    help: "TP = entry ± this × ATR",
  },
  // filters — toggles themselves are rendered as checkboxes by the Filters
  // section, not as generic Fields, so their meta entries are placeholders.
  use_htf_confirm: { label: "HTF confirm", type: "text" },
  htf_timeframe: {
    label: "HTF timeframe",
    type: "select",
    options: ["15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1w"],
    help: "bars sampled from this timeframe feed the HTF EMA",
  },
  htf_ema_period: {
    label: "HTF EMA period",
    type: "number",
    step: 1,
    min: 2,
  },
  use_adx_filter: { label: "ADX filter", type: "text" },
  filter_adx_period: {
    label: "ADX period",
    type: "number",
    step: 1,
    min: 2,
  },
  adx_min: {
    label: "ADX min",
    type: "number",
    step: 1,
    min: 0,
    help: "0 = don't require a minimum",
  },
  adx_max: {
    label: "ADX max",
    type: "number",
    step: 1,
    min: 0,
    help: "0 = don't require a maximum",
  },
  use_volume_filter: { label: "Volume filter", type: "text" },
  vol_ma_period: {
    label: "Volume MA period",
    type: "number",
    step: 1,
    min: 2,
  },
  vol_mult: {
    label: "Volume × median",
    type: "number",
    step: 0.1,
    min: 0,
    help: "1.2 = 20% above median",
  },
  use_atr_filter: { label: "ATR min filter", type: "text" },
  atr_min_pct: {
    label: "ATR min %",
    type: "number",
    step: 0.001,
    min: 0,
    help: "0.005 = 0.5% of price",
  },
  use_atr_max_filter: { label: "ATR max filter", type: "text" },
  atr_max_pct: {
    label: "ATR max %",
    type: "number",
    step: 0.001,
    min: 0,
    help: "0.03 = 3% of price",
  },
  use_time_filter: { label: "Time filter (UTC)", type: "text" },
  allowed_sessions: { label: "Allowed sessions", type: "text" },
  block_weekends: { label: "Block weekends", type: "boolean" },
  time_start_utc_mins: {
    label: "Start (min from midnight)",
    type: "number",
    step: 15,
    min: 0,
    help: "480 = 08:00 UTC",
  },
  time_end_utc_mins: {
    label: "End (min from midnight)",
    type: "number",
    step: 15,
    min: 0,
  },
  mr_regime_adx_max: {
    label: "MR regime ADX max",
    type: "number",
    step: 1,
    min: 0,
    help: "rsi_mean_reversion: require ADX < this; 0 = off. Uses filter ADX period.",
  },
  use_macd_confirm: { label: "MACD confirm", type: "text" },
  macd_fast: { label: "MACD fast", type: "number", step: 1, min: 2 },
  macd_slow: { label: "MACD slow", type: "number", step: 1, min: 2 },
  macd_signal: { label: "MACD signal", type: "number", step: 1, min: 2 },
};

interface Props {
  params: StrategyParams;
  strategies: StrategyInfo[];
  /** Curated symbol list for the dropdown. Empty = fall back to text input. */
  symbols?: string[];
  onChange: (params: StrategyParams) => void;
  disabled?: boolean;
  /** Hide the market (symbol/timeframe/bars) section. */
  hideMarket?: boolean;
}

export function StrategyForm({
  params,
  strategies,
  symbols,
  onChange,
  disabled,
  hideMarket,
}: Props) {
  const selected = strategies.find((s) => s.name === params.strategy);
  const strategyFields = useMemo(
    // strategies.py appends every filter toggle/sub-knob to each strategy's
    // hyperparams list; strip them here so they only appear in the Filters
    // section below instead of getting double-rendered.
    () => (selected?.hyperparams ?? []).filter((f) => !FILTER_FIELD_KEYS.has(f)),
    [selected]
  );

  const set = <K extends keyof StrategyParams>(
    key: K,
    value: StrategyParams[K]
  ) => onChange({ ...params, [key]: value });

  return (
    <div className="space-y-6">
      <div>
        <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Strategy
        </div>
        <div className="flex flex-wrap gap-2">
          {strategies.map((s) => {
            const active = s.name === params.strategy;
            return (
              <button
                key={s.name}
                type="button"
                disabled={disabled}
                onClick={() => set("strategy", s.name)}
                className={clsx(
                  "rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                  active
                    ? "border-slate-500 bg-slate-700 text-slate-100"
                    : "border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-700 hover:text-slate-200",
                  disabled && "opacity-50"
                )}
              >
                {prettyStrategy(s.name)}
              </button>
            );
          })}
        </div>
      </div>

      {!hideMarket && (
        <Section title="Market">
          <Grid>
            {MARKET_FIELDS.map((f) => (
              <Field
                key={f}
                name={f}
                value={params[f] as string | number}
                onChange={(v) => set(f, v as StrategyParams[typeof f])}
                disabled={disabled}
                options={f === "symbol" ? symbols : undefined}
              />
            ))}
          </Grid>
        </Section>
      )}

      {strategyFields.length > 0 && (
        <Section title="Strategy parameters">
          <Grid>
            {strategyFields.map((f) => (
              <Field
                key={f}
                name={f}
                value={params[f] as string | number | boolean}
                onChange={(v) => set(f, v as StrategyParams[typeof f])}
                disabled={disabled}
              />
            ))}
          </Grid>
        </Section>
      )}

      <Section title="Risk">
        <Grid>
          {RISK_FIELDS.map((f) => (
            <Field
              key={f}
              name={f}
              value={params[f] as string | number | boolean}
              onChange={(v) => set(f, v as StrategyParams[typeof f])}
              disabled={disabled}
            />
          ))}
        </Grid>
      </Section>

      <Section title="Filters (all opt-in, applied on top of the strategy)">
        <div className="space-y-4">
          {FILTER_GROUPS.map((group) => {
            const on = params[group.toggle] as boolean;
            return (
              <div
                key={group.toggle}
                className="rounded-md border border-slate-800 bg-slate-950/40 p-3"
              >
                <label className="flex items-start gap-2 text-xs text-slate-300">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 rounded border-slate-700 bg-slate-950 text-slate-400 focus:ring-1 focus:ring-slate-500"
                    disabled={disabled}
                    checked={on}
                    onChange={(e) =>
                      set(
                        group.toggle,
                        e.target.checked as StrategyParams[typeof group.toggle]
                      )
                    }
                  />
                  <span>
                    <span className="font-medium text-slate-200">
                      {group.label}
                    </span>
                    <span className="mt-0.5 block text-[10px] text-slate-500">
                      {group.help}
                    </span>
                  </span>
                </label>
                {group.fields.length > 0 && (
                  <div className="mt-3">
                    <Grid>
                      {group.fields.map((f) => (
                        <Field
                          key={f}
                          name={f}
                          value={params[f] as string | number}
                          onChange={(v) =>
                            set(f, v as StrategyParams[typeof f])
                          }
                          disabled={disabled || !on}
                        />
                      ))}
                    </Grid>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Section>

      {/* ---- Session filter ------------------------------------------- */}
      <Section title="Session filter (UTC)">
        <p className="mb-3 text-[11px] text-slate-500">
          Leave all unchecked to allow all sessions. Check specific sessions to
          restrict entries to those UTC windows only. Block weekends eliminates
          Saturday / Sunday bars.
        </p>
        <div className="flex flex-wrap gap-3">
          {(
            [
              { id: "asia", label: "Asia (00-07)" },
              { id: "london", label: "London (07-13)" },
              { id: "overlap", label: "Overlap (13-16)" },
              { id: "ny", label: "NY (16-22)" },
              { id: "off", label: "Off (22-24)" },
            ] as const
          ).map(({ id, label }) => {
            const checked = (params.allowed_sessions ?? []).includes(id);
            return (
              <label
                key={id}
                className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-300"
              >
                <input
                  type="checkbox"
                  disabled={disabled}
                  checked={checked}
                  className="h-4 w-4 rounded border-slate-700 bg-slate-950"
                  onChange={(e) => {
                    const current = params.allowed_sessions ?? [];
                    const next = e.target.checked
                      ? [...current, id]
                      : current.filter((s) => s !== id);
                    set("allowed_sessions", next as unknown as StrategyParams["allowed_sessions"]);
                  }}
                />
                {label}
              </label>
            );
          })}
        </div>
        <label className="mt-3 flex cursor-pointer items-center gap-1.5 text-xs text-slate-300">
          <input
            type="checkbox"
            disabled={disabled}
            checked={params.block_weekends ?? false}
            className="h-4 w-4 rounded border-slate-700 bg-slate-950"
            onChange={(e) => set("block_weekends", e.target.checked)}
          />
          Block weekends (Sat / Sun UTC)
        </label>
      </Section>

      <Section title="ATR sizing (volatility-scaled risk)">
        <label className="mb-3 inline-flex items-center gap-2 text-xs text-slate-300">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-slate-400 focus:ring-1 focus:ring-slate-500"
            disabled={disabled}
            checked={params.use_atr_sizing}
            onChange={(e) => set("use_atr_sizing", e.target.checked)}
          />
          Use ATR-based position sizing &amp; SL/TP
          <span className="text-[10px] text-slate-500">
            (overrides allocation / stop_loss_pct / take_profit_pct when on)
          </span>
        </label>
        <Grid>
          {ATR_FIELDS.map((f) => (
            <Field
              key={f}
              name={f}
              value={params[f] as number}
              onChange={(v) => set(f, v as StrategyParams[typeof f])}
              disabled={disabled || !params.use_atr_sizing}
            />
          ))}
        </Grid>
      </Section>
    </div>
  );
}

function prettyStrategy(name: string): string {
  return name
    .split("_")
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(" ");
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
        {title}
      </div>
      {children}
    </div>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">{children}</div>
  );
}

interface FieldProps {
  name: keyof StrategyParams;
  value: string | number | boolean;
  onChange: (value: string | number | boolean) => void;
  disabled?: boolean;
  /**
   * Dynamic option list provided by the caller. When present, overrides
   * the static type in FIELD_META and renders a <select>. Used for the
   * Symbol field so the curated list can come from the backend.
   */
  options?: string[];
}

function Field({ name, value, onChange, disabled, options }: FieldProps) {
  const meta = FIELD_META[name];
  if (!meta) return null;

  const base =
    "mt-1 w-full rounded-md border border-slate-800 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 focus:border-slate-600 focus:outline-none focus:ring-1 focus:ring-slate-600 disabled:opacity-50";

  // Caller-provided options (e.g. symbols from the backend) trump the
  // static FIELD_META type. If the current value isn't in the list
  // (saved run with an exotic symbol), prepend it so nothing is lost.
  const dynamicOptions = options && options.length > 0 ? options : null;
  const effectiveType = dynamicOptions ? "select" : meta.type;
  const selectOptions = dynamicOptions
    ? dynamicOptions.includes(String(value))
      ? dynamicOptions
      : [String(value), ...dynamicOptions]
    : meta.options ?? [];

  const input =
    effectiveType === "select" ? (
      <select
        className={base}
        disabled={disabled}
        value={String(value)}
        onChange={(e) => onChange(e.target.value)}
      >
        {selectOptions.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    ) : effectiveType === "text" ? (
      <input
        type="text"
        className={base}
        disabled={disabled}
        value={String(value)}
        onChange={(e) => onChange(e.target.value)}
      />
    ) : effectiveType === "boolean" ? (
      <input
        type="checkbox"
        className="mt-1 h-4 w-4 rounded border-slate-700 bg-slate-950 text-slate-400 focus:ring-1 focus:ring-slate-500"
        disabled={disabled}
        checked={Boolean(value)}
        onChange={(e) => onChange(e.target.checked)}
      />
    ) : (
      <input
        type="number"
        className={base}
        step={meta.step}
        min={meta.min}
        max={meta.max}
        disabled={disabled}
        value={Number(value)}
        onChange={(e) => {
          const n = Number(e.target.value);
          onChange(Number.isFinite(n) ? n : 0);
        }}
      />
    );

  return (
    <label className="block text-xs">
      <span className="text-slate-400">{meta.label}</span>
      {input}
      {meta.help && !dynamicOptions && (
        <span className="mt-0.5 block text-[10px] text-slate-500">
          {meta.help}
        </span>
      )}
    </label>
  );
}
