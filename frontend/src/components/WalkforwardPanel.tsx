import { useEffect, useMemo, useState } from "react";
import { clsx } from "clsx";
import type {
  ProfileMeta,
  StrategyParams,
  WalkforwardStabilityMatrix,
  WalkforwardStabilityResponse,
  WalkforwardStart,
  WalkforwardStatus,
} from "../types";
import { ProfileBar } from "./ProfileBar";
import {
  estimateWalkforwardWindows,
  suggestFixedOptMatrix,
} from "../walkforwardUtils";

interface Props {
  defaults: StrategyParams | null;
  params: StrategyParams | null;
  onParamsChange: (p: StrategyParams) => void;
  status: WalkforwardStatus | null;
  stability: WalkforwardStabilityResponse | null;
  onStart: (body: WalkforwardStart & { params: StrategyParams }) => Promise<void>;
  onCancel: () => Promise<void>;
  onDownloadStabilityCsv: () => Promise<void>;
  onDownloadWindowsCsv: () => Promise<void>;
  onDownloadReportJson: () => Promise<void>;
  busy: boolean;
  error: string | null;
  profiles: ProfileMeta[];
  profilesLoading?: boolean;
  activeProfile: string | null;
  onApplyProfile: (name: string) => Promise<StrategyParams | null>;
  onRefreshProfiles?: () => void;
}

/**
 * Walk-forward validation runner UI.
 *
 * Conceptually this is a "does my current config generalise?" test: we
 * slice the history into rolling (train, test) windows and show how the
 * test segments perform. A good-looking backtest that fails WF is a red
 * flag for overfit.
 *
 * We reuse the passed-in `params` (usually the same state as the Backtest
 * tab) so the user can calibrate → validate without retyping.
 */
export function WalkforwardPanel({
  defaults,
  params,
  onParamsChange,
  status,
  stability,
  onStart,
  onCancel,
  onDownloadStabilityCsv,
  onDownloadWindowsCsv,
  onDownloadReportJson,
  busy,
  error,
  profiles,
  profilesLoading,
  activeProfile,
  onApplyProfile,
  onRefreshProfiles,
}: Props) {
  const [trainBars, setTrainBars] = useState(500);
  const [testBars, setTestBars] = useState(200);
  const [step, setStep] = useState<number | "">("");
  const [mcSims, setMcSims] = useState(2000);
  const [trainEngine, setTrainEngine] = useState<"grid" | "optuna">("grid");
  const [optunaTrials, setOptunaTrials] = useState(64);
  const [optunaSeed, setOptunaSeed] = useState(42);
  const [optMatrixText, setOptMatrixText] = useState("");
  const [optError, setOptError] = useState<string | null>(null);

  const running = !!status?.running;
  const completed = status?.completed ?? 0;
  const total = status?.total ?? 0;
  const progressPct = total > 0 ? (completed / total) * 100 : 0;

  // ETA tick — same pattern as SweepPanel.
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, [running]);
  const eta = useMemo(() => computeEta(status, now), [status, now]);

  const canStart =
    !busy &&
    !running &&
    !!params &&
    !!defaults &&
    trainBars > 0 &&
    testBars > 0 &&
    (params.bars ?? 0) >= trainBars + testBars;

  const handleApplyProfile = async (name: string) => {
    setOptError(null);
    const merged = await onApplyProfile(name);
    if (merged) {
      setOptMatrixText(suggestFixedOptMatrix(merged));
    }
  };

  const handleStart = async () => {
    if (!params) return;
    setOptError(null);
    let optMatrix: Record<string, (string | number | boolean)[]> | undefined;
    if (optMatrixText.trim()) {
      try {
        const parsed = JSON.parse(optMatrixText) as unknown;
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("opt_matrix must be a JSON object.");
        }
        const clean: Record<string, (string | number | boolean)[]> = {};
        for (const [k, v] of Object.entries(parsed)) {
          if (!Array.isArray(v) || v.length === 0) {
            throw new Error(`opt_matrix.${k} must be a non-empty array.`);
          }
          for (const item of v) {
            if (!["string", "number", "boolean"].includes(typeof item)) {
              throw new Error(
                `opt_matrix.${k} contains unsupported value type.`
              );
            }
          }
          clean[k] = v as (string | number | boolean)[];
        }
        optMatrix = clean;
      } catch (e) {
        setOptError(e instanceof Error ? e.message : String(e));
        return;
      }
    }
    await onStart({
      params,
      train_bars: trainBars,
      test_bars: testBars,
      step: step === "" ? undefined : Number(step),
      mc_sims: Math.max(0, Math.floor(mcSims)),
      opt_matrix: optMatrix,
      train_engine: trainEngine,
      optuna_trials: Math.max(1, Math.floor(optunaTrials)),
      optuna_seed: Math.floor(optunaSeed),
    });
  };

  const updateBars = (n: number) => {
    if (!params) return;
    onParamsChange({ ...params, bars: Math.max(0, Math.floor(n)) });
  };

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="mb-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
            Walk-forward validation
          </h2>
          <p className="text-xs text-slate-500">
            Slide a rolling (train, test) window across history. Consistently
            positive <em>test</em> returns across windows ⇒ the strategy
            generalises. Good test on one window + losses elsewhere ⇒ overfit.
          </p>
        </div>

        <div className="mb-4">
          <ProfileBar
            profiles={profiles}
            loading={profilesLoading}
            activeName={activeProfile}
            disabled={running}
            applyOnly
            onApply={handleApplyProfile}
            onRefresh={onRefreshProfiles}
          />
          <p className="mt-2 text-[10px] text-slate-500">
            Apply loads the profile into walk-forward params (same as Backtest).
            <code className="ml-1 text-slate-400">opt_matrix</code> is set to
            lock key hyperparameters to the profile when possible.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <NumberField
            label="Total bars"
            help="Fetched from the exchange."
            value={params?.bars ?? 0}
            onChange={updateBars}
            disabled={running}
          />
          <NumberField
            label="Train bars"
            help="Each window's optimization slice."
            value={trainBars}
            onChange={setTrainBars}
            disabled={running}
          />
          <NumberField
            label="Test bars"
            help="Out-of-sample slice immediately after train."
            value={testBars}
            onChange={setTestBars}
            disabled={running}
          />
          <NumberField
            label="Step (optional)"
            help="Bars to advance between windows. Defaults to test bars."
            value={step === "" ? 0 : step}
            onChange={(v) => setStep(v <= 0 ? "" : v)}
            disabled={running}
          />
        </div>
        <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-3">
          <label className="block text-xs">
            <span className="text-slate-300">Train selection engine</span>
            <select
              className="mt-1 w-full rounded-md border border-slate-800 bg-slate-950 px-2 py-1.5 font-mono text-sm text-slate-100 focus:border-slate-600 focus:outline-none disabled:opacity-50"
              value={trainEngine}
              onChange={(e) =>
                setTrainEngine(e.target.value === "optuna" ? "optuna" : "grid")
              }
              disabled={running}
            >
              <option value="grid">Grid (exhaustive train search)</option>
              <option value="optuna">
                {"Optuna Bayesian (pip install optuna>=3)"}
              </option>
            </select>
            <span className="mt-1 block text-[10px] text-slate-500">
              Test metrics always use post-selection frozen params (OOS).
            </span>
          </label>
          <NumberField
            label="Optuna trials / window"
            help="Bounded by search-space size · API caps at 512."
            value={optunaTrials}
            onChange={setOptunaTrials}
            disabled={running || trainEngine !== "optuna"}
          />
          <NumberField
            label="Optuna seed"
            help="Sampler reproducibility seed."
            value={optunaSeed}
            onChange={setOptunaSeed}
            disabled={running || trainEngine !== "optuna"}
          />
        </div>
        <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
          <NumberField
            label="Monte Carlo sims"
            help="Trade-order bootstrap count for robustness stats."
            value={mcSims}
            onChange={setMcSims}
            disabled={running}
          />
          <label className="block text-xs">
            <span className="text-slate-300">opt_matrix (optional JSON)</span>
            <textarea
              className="mt-1 h-24 w-full rounded-md border border-slate-800 bg-slate-950 px-2 py-1 font-mono text-[11px] text-slate-100 focus:border-slate-600 focus:outline-none disabled:opacity-50"
              placeholder='Leave blank for strategy default grid, or {"donchian_period":[40]} to lock params'
              value={optMatrixText}
              onChange={(e) => setOptMatrixText(e.target.value)}
              disabled={running}
            />
            <span className="mt-1 block text-[10px] text-slate-500">
              Leave blank to use backend strategy-aware defaults.
            </span>
          </label>
        </div>

        <div className="mt-3 text-xs text-slate-500">
          {params ? (
            <>
              {activeProfile ? (
                <>
                  Profile{" "}
                  <span className="font-mono text-slate-300">
                    {activeProfile}
                  </span>
                  {" · "}
                </>
              ) : null}
              <span className="font-mono text-slate-300">
                {params.strategy}
              </span>{" "}
              on{" "}
              <span className="font-mono text-slate-300">
                {params.symbol} · {params.timeframe}
              </span>
              {params.use_atr_sizing && (
                <span className="ml-2 rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                  ATR
                </span>
              )}
              {params.use_adx_filter && (
                <span className="ml-1 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                  ADX
                </span>
              )}
              {params.use_htf_confirm && (
                <span className="ml-1 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                  HTF
                </span>
              )}
              {params.use_volume_filter && (
                <span className="ml-1 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                  Vol
                </span>
              )}
              . Expected windows (75% dev slice):{" "}
              <span className="font-mono text-slate-300">
                {estimateWalkforwardWindows(
                  params.bars,
                  trainBars,
                  testBars,
                  step
                )}
              </span>
            </>
          ) : (
            "Loading params…"
          )}
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
          {running && (
            <button
              type="button"
              onClick={onCancel}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
            >
              Cancel
            </button>
          )}
          <button
            type="button"
            onClick={handleStart}
            disabled={!canStart}
            className="rounded-md bg-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? "Running…" : "Start walk-forward"}
          </button>
        </div>

        {params && params.bars < trainBars + testBars && (
          <div className="mt-2 text-xs text-amber-400">
            Need at least train + test = {trainBars + testBars} bars; have{" "}
            {params.bars}.
          </div>
        )}
        {optError && (
          <div className="mt-2 text-xs text-bear">{optError}</div>
        )}
      </div>

      {(status || error) && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-300">
            Progress
          </h3>
          {status && (
            <div className="space-y-2 text-xs text-slate-400">
              <div className="flex items-center gap-2">
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-800">
                  <div
                    className={clsx(
                      "h-full transition-all",
                      status.error
                        ? "bg-bear"
                        : running
                        ? "bg-slate-400"
                        : "bg-bull"
                    )}
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
                <span className="font-mono text-slate-300">
                  {completed}/{total || "?"}
                </span>
              </div>
              {status.current && (
                <div className="text-[11px] text-slate-500">
                  Running window{" "}
                  <span className="font-mono text-slate-300">
                    {status.current.i + 1} of {status.current.of}
                  </span>
                </div>
              )}
              {running && eta && (
                <div className="flex gap-4 text-[11px] text-slate-500">
                  <span>
                    Elapsed:{" "}
                    <span className="font-mono text-slate-300">
                      {fmtSeconds(eta.elapsedSecs)}
                    </span>
                  </span>
                  <span>
                    Per window:{" "}
                    <span className="font-mono text-slate-300">
                      {fmtSeconds(eta.avgSecs, true)}
                    </span>
                  </span>
                  <span>
                    ETA:{" "}
                    <span className="font-mono text-slate-200">
                      {eta.remainingSecs != null
                        ? fmtSeconds(eta.remainingSecs)
                        : "—"}
                    </span>
                  </span>
                </div>
              )}
              {!running && status.finished_at && status.summary && (
                <div className="text-slate-500">
                  Completed in {fmtSeconds(
                    (status.finished_at ?? 0) - (status.started_at ?? 0)
                  )}
                  .
                </div>
              )}
              {status.error && (
                <div className="text-bear">
                  Error: {status.error.split("\n")[0]}
                </div>
              )}
            </div>
          )}
          {error && !status?.error && (
            <div className="mt-2 text-xs text-bear">{error}</div>
          )}
        </div>
      )}

      {status?.summary && status.windows.length > 0 && (
        <Results
          status={status}
          stabilityMatrix={stability?.matrix ?? status.summary.stability_matrix}
          onDownloadStabilityCsv={onDownloadStabilityCsv}
          onDownloadWindowsCsv={onDownloadWindowsCsv}
          onDownloadReportJson={onDownloadReportJson}
        />
      )}
    </div>
  );
}

// =====================================================================

function Results({
  status,
  stabilityMatrix,
  onDownloadStabilityCsv,
  onDownloadWindowsCsv,
  onDownloadReportJson,
}: {
  status: WalkforwardStatus;
  stabilityMatrix?: WalkforwardStabilityMatrix;
  onDownloadStabilityCsv: () => Promise<void>;
  onDownloadWindowsCsv: () => Promise<void>;
  onDownloadReportJson: () => Promise<void>;
}) {
  const s = status.summary!;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Windows" value={s.n_windows.toString()} />
        <StatCard
          label="Mean test return"
          value={`${s.mean_test_ret > 0 ? "+" : ""}${s.mean_test_ret.toFixed(2)}%`}
          tone={s.mean_test_ret > 0 ? "good" : s.mean_test_ret < 0 ? "bad" : undefined}
        />
        <StatCard
          label="Positive windows"
          value={`${s.positive_rate.toFixed(0)}%`}
          tone={
            s.positive_rate >= 60
              ? "good"
              : s.positive_rate >= 40
              ? undefined
              : "bad"
          }
        />
        <StatCard
          label="Verdict"
          value={s.verdict.replace("_", " ")}
          tone={
            s.verdict === "ROBUST"
              ? "good"
              : s.verdict === "NOT_VIABLE"
              ? "bad"
              : undefined
          }
        />
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Mean test MDD"
          value={`${(s.mean_test_mdd_pct ?? 0).toFixed(2)}%`}
        />
        <StatCard
          label="Unique selected cfgs"
          value={String(s.unique_selected_configs ?? 0)}
        />
        <StatCard
          label="Selection changes"
          value={`${(s.selection_transition_rate ?? 0).toFixed(0)}%`}
        />
        <StatCard
          label={
            status.train_engine === "optuna"
              ? "Train search (grid pts)"
              : "Candidates/window"
          }
          value={String(status.n_candidates ?? 0)}
        />
        {status.train_engine === "optuna" && (
          <>
            <StatCard
              label="Optuna trials cap"
              value={String(status.optuna_trials_effective ?? "—")}
            />
            <StatCard
              label="Optuna seed"
              value={String(status.optuna_seed ?? "—")}
            />
          </>
        )}
      </div>
      {s.trade_mc && s.trade_mc.sims > 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-300">
            Monte Carlo (trade order bootstrap)
          </h3>
          <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
            <MiniStat
              label="Sims"
              value={String(s.trade_mc.sims)}
            />
            <MiniStat
              label="Trades"
              value={String(s.trade_mc.n_trades)}
            />
            <MiniStat
              label="Return p05/p50/p95"
              value={`${s.trade_mc.ret_p05_pct.toFixed(2)} / ${s.trade_mc.ret_p50_pct.toFixed(2)} / ${s.trade_mc.ret_p95_pct.toFixed(2)}%`}
            />
            <MiniStat
              label="MDD mean/p95"
              value={`${s.trade_mc.mdd_mean_pct.toFixed(2)} / ${s.trade_mc.mdd_p95_pct.toFixed(2)}%`}
            />
          </div>
        </div>
      )}
      {s.final_oos && (
        <div className="rounded-xl border border-indigo-800/60 bg-indigo-950/20 p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-indigo-200">
            Final Holdout OOS (last 25%)
          </h3>
          <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
            <MiniStat
              label="Bars"
              value={String(s.final_oos.bars)}
            />
            <MiniStat
              label="Return %"
              value={`${s.final_oos.return_pct > 0 ? "+" : ""}${s.final_oos.return_pct.toFixed(2)}%`}
            />
            <MiniStat
              label="Trades / Win %"
              value={`${s.final_oos.trades} / ${s.final_oos.win_rate.toFixed(1)}%`}
            />
            <MiniStat
              label="MDD / PF"
              value={`${s.final_oos.max_drawdown_pct.toFixed(2)}% / ${s.final_oos.profit_factor.toFixed(2)}`}
            />
          </div>
          <div className="mt-2 text-[10px] text-indigo-200/80">
            Policy: {s.final_oos.policy ?? "—"} · selected windows:{" "}
            {s.final_oos.selected_windows ?? 0}
          </div>
        </div>
      )}
      {stabilityMatrix?.cells?.length ? (
        <StabilityHeatmap
          matrix={stabilityMatrix}
          onDownloadCsv={onDownloadStabilityCsv}
        />
      ) : null}

      <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="flex items-center justify-between px-4 py-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-300">
            Per-window results
          </h3>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800"
              onClick={() => void onDownloadWindowsCsv()}
            >
              Download windows CSV
            </button>
            <button
              type="button"
              className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800"
              onClick={() => void onDownloadReportJson()}
            >
              Download report JSON
            </button>
            <span className="text-[10px] text-slate-500">
              stdev {s.stdev_test_ret.toFixed(2)}% · median{" "}
              {s.median_test_ret.toFixed(2)}%
            </span>
          </div>
        </div>
        <div className="max-h-96 overflow-auto">
          <table className="min-w-full text-left text-xs">
            <thead className="sticky top-0 bg-slate-900/90 text-slate-500 backdrop-blur">
              <tr>
                <th className="px-4 py-1.5 font-medium">#</th>
                <th className="px-4 py-1.5 text-right font-medium">Train ret</th>
                <th className="px-4 py-1.5 text-right font-medium">Test ret</th>
                <th className="px-4 py-1.5 text-right font-medium">Train N</th>
                <th className="px-4 py-1.5 text-right font-medium">Test N</th>
                <th className="px-4 py-1.5 text-right font-medium">Win %</th>
                <th className="px-4 py-1.5 text-right font-medium">Max DD</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {status.windows.map((w) => (
                <tr
                  key={w.i}
                  className="border-t border-slate-800/60 hover:bg-slate-800/40"
                >
                  <td className="px-4 py-1.5 text-slate-400">{w.i + 1}</td>
                  <PctCell value={w.train_ret} />
                  <PctCell value={w.test_ret} bold />
                  <td className="px-4 py-1.5 text-right text-slate-400">
                    {w.train_n}
                  </td>
                  <td className="px-4 py-1.5 text-right text-slate-400">
                    {w.test_n}
                  </td>
                  <td className="px-4 py-1.5 text-right text-slate-400">
                    {w.test_wr.toFixed(1)}
                  </td>
                  <td className="px-4 py-1.5 text-right text-slate-400">
                    {w.test_mdd.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/40 p-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className="mt-1 font-mono text-slate-200">{value}</div>
    </div>
  );
}

function StabilityHeatmap({
  matrix,
  onDownloadCsv,
}: {
  matrix: WalkforwardStabilityMatrix;
  onDownloadCsv: () => Promise<void>;
}) {
  const xVals = Array.from(new Set(matrix.cells.map((c) => String(c.x))));
  const yVals = Array.from(new Set(matrix.cells.map((c) => String(c.y))));
  const xSort = [...xVals].sort((a, b) => cmpNumericMaybe(a, b));
  const ySort = [...yVals].sort((a, b) => cmpNumericMaybe(a, b));
  const maxAbsRet =
    Math.max(
      0.01,
      ...matrix.cells.map((c) => Math.abs(c.mean_test_ret))
    ) || 1;
  const cellMap = new Map(
    matrix.cells.map((c) => [`${String(c.x)}|${String(c.y)}`, c] as const)
  );
  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="flex items-center justify-between px-4 py-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-300">
          Stability heatmap
        </h3>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-slate-500">
            Color = mean test return · opacity = sample windows
          </span>
          <button
            type="button"
            className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800"
            onClick={() => {
              void onDownloadCsv();
            }}
          >
            Download CSV
          </button>
        </div>
      </div>
      <div className="overflow-auto px-4 pb-4">
        <table className="min-w-max text-xs">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-slate-900/90 px-2 py-1 text-left text-slate-500">
                {matrix.y_key ?? "y"} \ {matrix.x_key ?? "x"}
              </th>
              {xSort.map((x) => (
                <th key={x} className="px-2 py-1 text-slate-500">
                  {x}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ySort.map((y) => (
              <tr key={y} className="border-t border-slate-800/60">
                <td className="sticky left-0 z-10 bg-slate-900/90 px-2 py-1 text-slate-500">
                  {y}
                </td>
                {xSort.map((x) => {
                  const c = cellMap.get(`${x}|${y}`);
                  const ret = c?.mean_test_ret ?? 0;
                  const alpha = c ? Math.min(1, 0.25 + c.n_windows * 0.15) : 0.1;
                  const tone =
                    ret > 0
                      ? `rgba(34,197,94,${alpha})`
                      : ret < 0
                      ? `rgba(239,68,68,${alpha})`
                      : `rgba(100,116,139,${alpha})`;
                  return (
                    <td key={`${x}-${y}`} className="px-1 py-1">
                      <div
                        className="min-w-20 rounded px-2 py-1 font-mono text-[11px]"
                        style={{
                          backgroundColor: tone,
                          border: "1px solid rgba(148,163,184,0.2)",
                        }}
                        title={
                          c
                            ? `ret=${c.mean_test_ret.toFixed(2)}%, mdd=${c.mean_test_mdd.toFixed(2)}%, windows=${c.n_windows}, positive=${c.positive_rate.toFixed(0)}%`
                            : "No selections in this cell."
                        }
                      >
                        {c ? (
                          <>
                            <div>{fmtSigned(c.mean_test_ret)}%</div>
                            <div className="text-[10px] text-slate-100/90">
                              n={c.n_windows}
                            </div>
                          </>
                        ) : (
                          <div className="text-slate-200/50">—</div>
                        )}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-4 pb-3 text-[10px] text-slate-500">
        Max |mean test return| in grid: {maxAbsRet.toFixed(2)}%
      </div>
    </div>
  );
}

function cmpNumericMaybe(a: string, b: string): number {
  const na = Number(a);
  const nb = Number(b);
  if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
  return a.localeCompare(b);
}

function fmtSigned(v: number): string {
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}`;
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div
        className={clsx(
          "mt-1 font-mono text-lg font-semibold",
          tone === "good" && "text-bull",
          tone === "bad" && "text-bear",
          !tone && "text-slate-100"
        )}
      >
        {value}
      </div>
    </div>
  );
}

function PctCell({ value, bold }: { value: number; bold?: boolean }) {
  return (
    <td
      className={clsx(
        "px-4 py-1.5 text-right",
        value > 0 ? "text-bull" : value < 0 ? "text-bear" : "text-slate-400",
        bold && "font-semibold"
      )}
    >
      {value > 0 ? "+" : ""}
      {value.toFixed(2)}%
    </td>
  );
}

function NumberField({
  label,
  help,
  value,
  onChange,
  disabled,
}: {
  label: string;
  help?: string;
  value: number;
  onChange: (n: number) => void;
  disabled?: boolean;
}) {
  return (
    <label className="block text-xs">
      <span className="text-slate-300">{label}</span>
      <input
        type="number"
        min={0}
        className="mt-1 w-full rounded-md border border-slate-800 bg-slate-950 px-2 py-1 font-mono text-sm text-slate-100 focus:border-slate-600 focus:outline-none disabled:opacity-50"
        value={value || ""}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        disabled={disabled}
      />
      {help && <span className="mt-1 block text-[10px] text-slate-500">{help}</span>}
    </label>
  );
}

function fmtSeconds(secs: number, allowFractional = false): string {
  if (!Number.isFinite(secs) || secs < 0) return "—";
  if (allowFractional && secs < 10) return `${secs.toFixed(1)}s`;
  const s = Math.round(secs);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m < 60) return r ? `${m}m ${r}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function computeEta(
  status: WalkforwardStatus | null,
  now: number
): {
  elapsedSecs: number;
  avgSecs: number;
  remainingSecs: number | null;
} | null {
  if (!status || !status.started_at) return null;
  const elapsedSecs = Math.max(0, now - status.started_at);
  const remainingCount = Math.max(0, status.total - status.completed);
  if (status.completed <= 0) {
    return { elapsedSecs, avgSecs: 0, remainingSecs: null };
  }
  const avgSecs = elapsedSecs / status.completed;
  return {
    elapsedSecs,
    avgSecs,
    remainingSecs: avgSecs * remainingCount,
  };
}
