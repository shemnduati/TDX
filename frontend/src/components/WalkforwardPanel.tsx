import { useEffect, useMemo, useState } from "react";
import { clsx } from "clsx";
import type { StrategyParams, WalkforwardStatus } from "../types";

interface Props {
  defaults: StrategyParams | null;
  params: StrategyParams | null;
  onParamsChange: (p: StrategyParams) => void;
  status: WalkforwardStatus | null;
  onStart: (body: {
    params: StrategyParams;
    train_bars: number;
    test_bars: number;
    step?: number;
  }) => Promise<void>;
  onCancel: () => Promise<void>;
  busy: boolean;
  error: string | null;
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
  onStart,
  onCancel,
  busy,
  error,
}: Props) {
  const [trainBars, setTrainBars] = useState(500);
  const [testBars, setTestBars] = useState(200);
  const [step, setStep] = useState<number | "">("");

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

  const handleStart = async () => {
    if (!params) return;
    await onStart({
      params,
      train_bars: trainBars,
      test_bars: testBars,
      step: step === "" ? undefined : Number(step),
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

        <div className="mt-3 text-xs text-slate-500">
          {params ? (
            <>
              Using current Backtest params:{" "}
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
              . Expected windows:{" "}
              <span className="font-mono text-slate-300">
                {estimateWindows(params.bars, trainBars, testBars, step)}
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
        <Results status={status} />
      )}
    </div>
  );
}

// =====================================================================

function Results({ status }: { status: WalkforwardStatus }) {
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

      <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="flex items-center justify-between px-4 py-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-300">
            Per-window results
          </h3>
          <span className="text-[10px] text-slate-500">
            stdev {s.stdev_test_ret.toFixed(2)}% · median{" "}
            {s.median_test_ret.toFixed(2)}%
          </span>
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

function estimateWindows(
  bars: number,
  trainBars: number,
  testBars: number,
  step: number | ""
): string {
  if (!bars || !trainBars || !testBars) return "—";
  if (bars < trainBars + testBars) return "0";
  const s = step === "" || !step ? testBars : step;
  return String(Math.floor((bars - trainBars - testBars) / s) + 1);
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
