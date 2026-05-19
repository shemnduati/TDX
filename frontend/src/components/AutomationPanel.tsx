import { useState } from "react";
import type {
  DivergenceResponse,
  ReadinessResponse,
  TournamentRunResponse,
} from "../types";

interface Props {
  busy: boolean;
  error: string | null;
  tournament: TournamentRunResponse | null;
  divergence: DivergenceResponse | null;
  readiness: ReadinessResponse | null;
  onRunTournament: () => Promise<void>;
  onCheckDivergence: (thresholds: Record<string, number>) => Promise<void>;
  onCheckReadiness: (thresholds: Record<string, number>) => Promise<void>;
}

export function AutomationPanel({
  busy,
  error,
  tournament,
  divergence,
  readiness,
  onRunTournament,
  onCheckDivergence,
  onCheckReadiness,
}: Props) {
  const [showRows, setShowRows] = useState(false);
  const [maxReturnDelta, setMaxReturnDelta] = useState(2.0);
  const [maxTradeDeltaAbs, setMaxTradeDeltaAbs] = useState(2.0);
  const [minTsMatch, setMinTsMatch] = useState(50.0);
  const [maxPnlDeltaPct, setMaxPnlDeltaPct] = useState(1.5);
  const [readinessMinAvgTsMatch, setReadinessMinAvgTsMatch] = useState(60.0);
  const [readinessMaxAvgPnlDelta, setReadinessMaxAvgPnlDelta] = useState(2.0);

  const thresholds = {
    max_return_delta_pct: maxReturnDelta,
    max_trade_count_delta_abs: maxTradeDeltaAbs,
    min_timestamp_match_rate: minTsMatch,
    max_mean_abs_pnl_delta_pct: maxPnlDeltaPct,
  };
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Automation & Monitoring
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Weekly tournament promotion decisions and live-vs-backtest divergence
          checks for shadow-trading readiness.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onRunTournament}
            disabled={busy}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
          >
            Run tournament (dry-run)
          </button>
          <button
            type="button"
            onClick={() => onCheckDivergence(thresholds)}
            disabled={busy}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
          >
            Check divergence
          </button>
          <button
            type="button"
            onClick={() =>
              onCheckReadiness({
                ...thresholds,
                min_avg_timestamp_match_rate: readinessMinAvgTsMatch,
                max_avg_mean_abs_pnl_delta_pct: readinessMaxAvgPnlDelta,
              })
            }
            disabled={busy}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
          >
            30d readiness
          </button>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs lg:grid-cols-4">
          <Num label="Max return delta %" value={maxReturnDelta} onChange={setMaxReturnDelta} step={0.25} />
          <Num label="Max trade delta abs" value={maxTradeDeltaAbs} onChange={setMaxTradeDeltaAbs} step={1} />
          <Num label="Min TS match %" value={minTsMatch} onChange={setMinTsMatch} step={5} />
          <Num label="Max mean PnL delta %" value={maxPnlDeltaPct} onChange={setMaxPnlDeltaPct} step={0.25} />
          <Num
            label="Readiness min avg TS %"
            value={readinessMinAvgTsMatch}
            onChange={setReadinessMinAvgTsMatch}
            step={5}
          />
          <Num
            label="Readiness max avg PnL %"
            value={readinessMaxAvgPnlDelta}
            onChange={setReadinessMaxAvgPnlDelta}
            step={0.25}
          />
        </div>
        {error && <p className="mt-2 text-xs text-rose-300">{error}</p>}
      </div>

      {tournament && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-xs">
          <p className="text-slate-200">
            Tournament: promoted {tournament.promoted}, candidate{" "}
            {tournament.candidate}, demoted {tournament.demoted} (ok{" "}
            {tournament.ok}/{tournament.total})
          </p>
          {tournament.effective_engine && (
            <p className="mt-1 text-slate-400">
              engine: requested {tournament.requested_engine ?? "n/a"} → effective{" "}
              {tournament.effective_engine}
              {tournament.fallback_reason ? " (fallback applied)" : ""}
            </p>
          )}
          <button
            type="button"
            onClick={() => setShowRows((v) => !v)}
            className="mt-2 text-slate-400 underline"
          >
            {showRows ? "Hide rows" : "Show rows"}
          </button>
          {showRows && (
            <div className="mt-2 max-h-56 overflow-auto rounded border border-slate-800 p-2 font-mono text-[11px]">
              {tournament.rows.map((r) => (
                <div key={r.name} className="py-0.5">
                  {r.name} · {r.deployment_status ?? "n/a"} ·{" "}
                  {r.tournament_score?.toFixed(3) ?? "—"}
                  {r.error ? ` · ${r.error}` : ""}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {divergence && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-xs">
          <p className="text-slate-200">
            Divergence: {divergence.symbol} {divergence.timeframe} · verdict{" "}
            <span
              className={
                divergence.verdict === "aligned"
                  ? "text-emerald-300"
                  : "text-rose-300"
              }
            >
              {divergence.verdict}
            </span>
          </p>
          <p className="mt-1 text-slate-400">
            Return delta {divergence.return_delta_pct.toFixed(2)}% · Trade delta{" "}
            {divergence.trade_count_delta} · TS match{" "}
            {divergence.timestamp_match_rate.toFixed(1)}%
          </p>
          <p className="mt-1 text-slate-500">
            matched {divergence.matched_trades} · unmatched L/B{" "}
            {divergence.unmatched_live_trades}/{divergence.unmatched_backtest_trades}
            {" · "}
            mean abs pnl delta {divergence.mean_abs_pnl_delta_pct.toFixed(2)}%
          </p>
        </div>
      )}

      {readiness && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-xs">
          <p className="text-slate-200">
            Readiness {readiness.days}d:{" "}
            <span
              className={
                readiness.summary.verdict === "READY"
                  ? "text-emerald-300"
                  : readiness.summary.verdict === "NO_DATA"
                  ? "text-slate-400"
                  : "text-amber-300"
              }
            >
              {readiness.summary.verdict}
            </span>
          </p>
          <p className="mt-1 text-slate-400">
            aligned {readiness.summary.aligned}/{readiness.summary.samples} (
            {readiness.summary.aligned_pct.toFixed(1)}%)
          </p>
          <p className="mt-1 text-slate-500">
            avg TS match {readiness.summary.avg_timestamp_match_rate.toFixed(1)}% ·
            avg mean abs pnl delta{" "}
            {readiness.summary.avg_mean_abs_pnl_delta_pct.toFixed(2)}%
          </p>
        </div>
      )}
    </div>
  );
}

function Num({
  label,
  value,
  onChange,
  step,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step: number;
}) {
  return (
    <label className="block">
      <span className="text-slate-400">{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}
