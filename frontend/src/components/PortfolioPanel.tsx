import { useMemo, useState } from "react";
import type {
  PortfolioRiskConfig,
  PortfolioRunResponse,
  StrategyInfo,
  StrategyParams,
} from "../types";

interface Props {
  params: StrategyParams | null;
  strategies: StrategyInfo[];
  busy: boolean;
  error: string | null;
  result: PortfolioRunResponse | null;
  onRun: (
    weights: Record<string, number>,
    risk: PortfolioRiskConfig
  ) => Promise<void>;
}

const DEFAULT_RISK: PortfolioRiskConfig = {
  max_open_positions: 4,
  max_correlated_positions: 2,
  vol_target_atr_pct: 0.015,
  vol_scale_min: 0.25,
  vol_scale_max: 2.0,
  circuit_ema_fast: 20,
  circuit_ema_slow: 60,
  circuit_sigma: 2.0,
  max_positions_per_group: 2,
  risk_budget_overrides: {},
  correlation_groups: {},
};

export function PortfolioPanel({
  params,
  strategies,
  busy,
  error,
  result,
  onRun,
}: Props) {
  const [weightsText, setWeightsText] = useState(
    '{"ema_crossover": 0.5, "rsi_mean_reversion": 0.5}'
  );
  const [risk, setRisk] = useState<PortfolioRiskConfig>(DEFAULT_RISK);
  const [riskBudgetText, setRiskBudgetText] = useState("{}");
  const [corrGroupsText, setCorrGroupsText] = useState("{}");
  const [parseError, setParseError] = useState<string | null>(null);

  const known = useMemo(() => new Set(strategies.map((s) => s.name)), [strategies]);

  const handleRun = async () => {
    setParseError(null);
    let weights: Record<string, number>;
    try {
      const raw = JSON.parse(weightsText) as unknown;
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
        throw new Error("weights must be a JSON object");
      }
      weights = Object.fromEntries(
        Object.entries(raw).map(([k, v]) => [k, Number(v)])
      );
      if (!Object.keys(weights).length) {
        throw new Error("weights must include at least one strategy");
      }
      for (const [k, v] of Object.entries(weights)) {
        if (!known.has(k)) {
          throw new Error(`Unknown strategy in weights: ${k}`);
        }
        if (!Number.isFinite(v)) {
          throw new Error(`Invalid numeric weight for ${k}`);
        }
      }
    } catch (e) {
      setParseError(e instanceof Error ? e.message : String(e));
      return;
    }
    let riskBudgets: Record<string, number> = {};
    let corrGroups: Record<string, string> = {};
    try {
      const rb = JSON.parse(riskBudgetText) as unknown;
      const cg = JSON.parse(corrGroupsText) as unknown;
      if (!rb || typeof rb !== "object" || Array.isArray(rb)) {
        throw new Error("risk budget overrides must be a JSON object");
      }
      if (!cg || typeof cg !== "object" || Array.isArray(cg)) {
        throw new Error("correlation groups must be a JSON object");
      }
      riskBudgets = Object.fromEntries(
        Object.entries(rb).map(([k, v]) => [k, Number(v)])
      );
      corrGroups = Object.fromEntries(
        Object.entries(cg).map(([k, v]) => [k, String(v)])
      );
      for (const [k, v] of Object.entries(riskBudgets)) {
        if (!known.has(k)) {
          throw new Error(`Unknown strategy in risk budgets: ${k}`);
        }
        if (!Number.isFinite(v) || v < 0) {
          throw new Error(`Invalid non-negative risk budget for ${k}`);
        }
      }
      for (const [k, v] of Object.entries(corrGroups)) {
        if (!known.has(k)) {
          throw new Error(`Unknown strategy in correlation groups: ${k}`);
        }
        if (!v.trim()) {
          throw new Error(`Empty correlation group for ${k}`);
        }
      }
    } catch (e) {
      setParseError(e instanceof Error ? e.message : String(e));
      return;
    }
    await onRun(weights, {
      ...risk,
      risk_budget_overrides: riskBudgets,
      correlation_groups: corrGroups,
    });
  };

  const c = result?.result.combined;
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Portfolio runner
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Concurrent multi-strategy replay with risk caps, ATR vol-target
          scaling, and equity-curve circuit breaker.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
          <label className="block text-xs">
            <span className="text-slate-300">Weights JSON</span>
            <textarea
              className="mt-1 h-24 w-full rounded-md border border-slate-800 bg-slate-950 px-2 py-1 font-mono text-[11px] text-slate-100 focus:border-slate-600 focus:outline-none"
              value={weightsText}
              onChange={(e) => setWeightsText(e.target.value)}
            />
          </label>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <Field label="Max open" value={risk.max_open_positions} onChange={(n) => setRisk((r) => ({ ...r, max_open_positions: n }))} />
            <Field label="Max correlated" value={risk.max_correlated_positions} onChange={(n) => setRisk((r) => ({ ...r, max_correlated_positions: n }))} />
            <Field label="Vol target ATR%" value={risk.vol_target_atr_pct} onChange={(n) => setRisk((r) => ({ ...r, vol_target_atr_pct: n }))} step={0.001} />
            <Field label="Circuit sigma" value={risk.circuit_sigma} onChange={(n) => setRisk((r) => ({ ...r, circuit_sigma: n }))} step={0.1} />
            <Field label="EMA fast" value={risk.circuit_ema_fast} onChange={(n) => setRisk((r) => ({ ...r, circuit_ema_fast: n }))} />
            <Field label="EMA slow" value={risk.circuit_ema_slow} onChange={(n) => setRisk((r) => ({ ...r, circuit_ema_slow: n }))} />
            <Field
              label="Max/group"
              value={risk.max_positions_per_group}
              onChange={(n) =>
                setRisk((r) => ({ ...r, max_positions_per_group: n }))
              }
            />
          </div>
        </div>
        <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
          <label className="block text-xs">
            <span className="text-slate-300">Risk budget overrides (JSON)</span>
            <textarea
              className="mt-1 h-20 w-full rounded-md border border-slate-800 bg-slate-950 px-2 py-1 font-mono text-[11px] text-slate-100 focus:border-slate-600 focus:outline-none"
              value={riskBudgetText}
              onChange={(e) => setRiskBudgetText(e.target.value)}
              placeholder='{"ema_crossover": 0.3, "rsi_mean_reversion": 0.7}'
            />
          </label>
          <label className="block text-xs">
            <span className="text-slate-300">Correlation groups (JSON)</span>
            <textarea
              className="mt-1 h-20 w-full rounded-md border border-slate-800 bg-slate-950 px-2 py-1 font-mono text-[11px] text-slate-100 focus:border-slate-600 focus:outline-none"
              value={corrGroupsText}
              onChange={(e) => setCorrGroupsText(e.target.value)}
              placeholder='{"ema_crossover": "trend", "donchian_breakout": "trend"}'
            />
          </label>
        </div>
        <div className="mt-3 flex items-center justify-end">
          <button
            type="button"
            onClick={handleRun}
            disabled={!params || busy}
            className="rounded-md bg-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Running..." : "Run portfolio"}
          </button>
        </div>
        {(parseError || error) && (
          <p className="mt-2 text-xs text-rose-300">{parseError || error}</p>
        )}
      </div>

      {c && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-xs">
          <p className="font-mono text-slate-200">
            Return {c.return_pct.toFixed(3)}% · Balance {c.balance.toFixed(2)} ·
            Trades {c.total_trades}
          </p>
          <p className="mt-1 text-slate-400">
            MDD {c.max_drawdown_pct.toFixed(2)}% · Skips (risk/corr/circuit):{" "}
            {c.skipped_by_risk_limit}/{c.skipped_by_corr_limit}/
            {c.skipped_by_circuit}
          </p>
          <p className="mt-1 text-slate-500">
            Group skips: {c.skipped_by_group_limit} · Halted bars:{" "}
            {c.circuit_halted_bars}
          </p>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  step = 1,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  step?: number;
}) {
  return (
    <label className="block">
      <span className="text-slate-400">{label}</span>
      <input
        type="number"
        className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
        value={value}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}
