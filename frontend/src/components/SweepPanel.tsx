import { useEffect, useMemo, useState } from "react";
import { clsx } from "clsx";
import type { StrategyParams, SweepStatus } from "../types";

/** Fields that make sense to sweep. Curated so the UI isn't overwhelming. */
const SWEEPABLE: {
  key: keyof StrategyParams;
  label: string;
  defaultGrid: string;
  help?: string;
}[] = [
  { key: "strategy", label: "Strategy", defaultGrid: "ema_crossover, donchian_breakout" },
  { key: "timeframe", label: "Timeframe", defaultGrid: "1h, 4h" },
  { key: "symbol", label: "Symbol", defaultGrid: "BTC/USDT, ETH/USDT" },
  { key: "ema_short", label: "EMA short", defaultGrid: "12, 20" },
  { key: "ema_long", label: "EMA long", defaultGrid: "26, 50" },
  { key: "ema_trend", label: "Trend filter", defaultGrid: "0, 200" },
  { key: "donchian_period", label: "Donchian period", defaultGrid: "20, 55" },
  { key: "rsi_oversold", label: "RSI oversold", defaultGrid: "25, 30, 35" },
  { key: "rsi_overbought", label: "RSI overbought", defaultGrid: "65, 70, 75" },
  { key: "stop_loss_pct", label: "Stop loss", defaultGrid: "0.02, 0.03" },
  { key: "take_profit_pct", label: "Take profit", defaultGrid: "0.04, 0.06" },
  { key: "atr_stop_mult", label: "ATR stop ×", defaultGrid: "1.5, 2, 2.5" },
  { key: "atr_tp_mult", label: "ATR take ×", defaultGrid: "2, 3, 4" },
];

interface Props {
  defaults: StrategyParams | null;
  status: SweepStatus | null;
  onStart: (body: {
    base_params: Partial<StrategyParams>;
    matrix: Record<string, (string | number | boolean)[]>;
    label_prefix: string;
  }) => Promise<void>;
  onCancel: () => Promise<void>;
  onJumpToHistory: () => void;
  busy: boolean;
  error: string | null;
}

export function SweepPanel({
  defaults,
  status,
  onStart,
  onCancel,
  onJumpToHistory,
  busy,
  error,
}: Props) {
  // Which fields the user has selected to sweep, keyed by field name.
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [prefix, setPrefix] = useState("sweep");

  const toggleField = (key: string) => {
    setSelected((prev) => {
      const next = { ...prev };
      if (key in next) {
        delete next[key];
      } else {
        const def =
          SWEEPABLE.find((s) => s.key === key)?.defaultGrid ?? "";
        next[key] = def;
      }
      return next;
    });
  };

  const parsedMatrix = useMemo(() => {
    const out: Record<string, (string | number | boolean)[]> = {};
    for (const [key, raw] of Object.entries(selected)) {
      const values = raw
        .split(/[,;\n]/)
        .map((s) => s.trim())
        .filter(Boolean)
        .map((s) => coerce(key as keyof StrategyParams, s));
      if (values.length > 0) out[key] = values;
    }
    return out;
  }, [selected]);

  const totalConfigs = Object.values(parsedMatrix).reduce(
    (acc, v) => acc * v.length,
    1
  );
  const canStart =
    !busy &&
    !!defaults &&
    Object.keys(parsedMatrix).length > 0 &&
    totalConfigs > 0 &&
    totalConfigs <= 200 &&
    !(status?.running ?? false);

  const progressPct =
    status && status.total > 0 ? (status.completed / status.total) * 100 : 0;

  // Tick once a second while a sweep is running so the ETA ages between polls.
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!status?.running) return;
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, [status?.running]);

  const eta = useMemo(() => computeEta(status, now), [status, now]);

  const handleStart = async () => {
    if (!defaults) return;
    await onStart({
      base_params: defaults,
      matrix: parsedMatrix,
      label_prefix: prefix.trim() || "sweep",
    });
  };

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="mb-3 flex items-baseline justify-between">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
              Parameter grid
            </h2>
            <p className="text-xs text-slate-500">
              Pick fields to sweep and enter comma-separated values for each.
              Every combination runs as its own backtest and gets saved to
              History.
            </p>
          </div>
          <label className="block text-xs text-slate-400">
            Label prefix
            <input
              type="text"
              className="ml-2 rounded-md border border-slate-800 bg-slate-950 px-2 py-1 text-sm text-slate-100 focus:border-slate-600 focus:outline-none"
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
              disabled={busy || status?.running}
            />
          </label>
        </div>

        <div className="mb-4 flex flex-wrap gap-2">
          {SWEEPABLE.map((s) => {
            const active = s.key in selected;
            return (
              <button
                key={s.key}
                type="button"
                disabled={status?.running}
                onClick={() => toggleField(s.key)}
                className={clsx(
                  "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                  active
                    ? "border-slate-500 bg-slate-700 text-slate-100"
                    : "border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-700 hover:text-slate-200",
                  status?.running && "opacity-50"
                )}
              >
                {s.label}
              </button>
            );
          })}
        </div>

        {Object.keys(selected).length === 0 ? (
          <div className="rounded-md border border-dashed border-slate-800 p-4 text-center text-xs text-slate-500">
            Tap a field above to add it to the grid.
          </div>
        ) : (
          <div className="space-y-2">
            {Object.entries(selected).map(([key, raw]) => {
              const meta = SWEEPABLE.find((s) => s.key === key);
              const parsed = parsedMatrix[key] ?? [];
              return (
                <div
                  key={key}
                  className="grid grid-cols-[140px_1fr_auto] items-center gap-3 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2"
                >
                  <span className="text-xs font-medium text-slate-300">
                    {meta?.label ?? key}
                  </span>
                  <input
                    type="text"
                    className="w-full rounded-md border border-slate-800 bg-slate-950 px-2 py-1 font-mono text-xs text-slate-100 focus:border-slate-600 focus:outline-none"
                    value={raw}
                    onChange={(e) =>
                      setSelected((prev) => ({ ...prev, [key]: e.target.value }))
                    }
                    disabled={status?.running}
                    placeholder={meta?.defaultGrid}
                  />
                  <span className="text-[10px] tabular-nums text-slate-500">
                    {parsed.length} value{parsed.length === 1 ? "" : "s"}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <div className="text-xs text-slate-400">
            {totalConfigs > 0 && Object.keys(parsedMatrix).length > 0 ? (
              <>
                <span className="font-mono text-slate-200">{totalConfigs}</span>{" "}
                configuration{totalConfigs === 1 ? "" : "s"}
                {totalConfigs > 200 && (
                  <span className="ml-2 text-amber-400">
                    (too many, max 200)
                  </span>
                )}
              </>
            ) : (
              "Pick at least one field with values."
            )}
          </div>
          <div className="flex gap-2">
            {status?.running && (
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
              {status?.running ? "Running…" : "Start sweep"}
            </button>
          </div>
        </div>
      </div>

      {(status || error) && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-300">
              Progress
            </h3>
            {status?.results?.length ? (
              <button
                type="button"
                onClick={onJumpToHistory}
                className="text-xs text-slate-400 hover:text-slate-200 hover:underline"
              >
                View in History →
              </button>
            ) : null}
          </div>

          {status && (
            <div className="space-y-2 text-xs text-slate-400">
              <div className="flex items-center gap-2">
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-800">
                  <div
                    className={clsx(
                      "h-full transition-all",
                      status.error
                        ? "bg-bear"
                        : status.running
                        ? "bg-slate-400"
                        : "bg-bull"
                    )}
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
                <span className="font-mono text-slate-300">
                  {status.completed}/{status.total}
                </span>
              </div>
              {status.current && (
                <div className="font-mono text-[11px] text-slate-500">
                  Now running:{" "}
                  {Object.entries(status.current)
                    .map(([k, v]) => `${k}=${v}`)
                    .join(" · ")}
                </div>
              )}
              {status.running && eta && (
                <div className="flex gap-4 text-[11px] text-slate-500">
                  <span>
                    Elapsed:{" "}
                    <span className="font-mono text-slate-300">
                      {fmtSeconds(eta.elapsedSecs)}
                    </span>
                  </span>
                  <span>
                    Per config:{" "}
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
              {!status.running && status.finished_at && (
                <div className="text-slate-500">
                  {status.error ? (
                    <span className="text-bear">
                      Error: {status.error.split("\n")[0]}
                    </span>
                  ) : (
                    <>Completed in {fmtDuration(status)}.</>
                  )}
                </div>
              )}
            </div>
          )}

          {error && !status?.error && (
            <div className="mt-2 text-xs text-bear">{error}</div>
          )}
        </div>
      )}

      {status && status.results.length > 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60">
          <div className="flex items-center justify-between p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-300">
              Results ({status.results.length})
            </h3>
            <span className="text-[10px] text-slate-500">
              sorted by return %
            </span>
          </div>
          <div className="max-h-96 overflow-auto">
            <table className="min-w-full text-left text-xs">
              <thead className="sticky top-0 bg-slate-900/90 text-slate-500 backdrop-blur">
                <tr>
                  <th className="px-4 py-1.5 font-medium">Label</th>
                  <th className="px-4 py-1.5 text-right font-medium">Trades</th>
                  <th className="px-4 py-1.5 text-right font-medium">Win %</th>
                  <th className="px-4 py-1.5 text-right font-medium">Return</th>
                  <th className="px-4 py-1.5 text-right font-medium">Max DD</th>
                  <th className="px-4 py-1.5 text-right font-medium">PF</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {[...status.results]
                  .sort(
                    (a, b) =>
                      (b.summary?.return_pct ?? 0) -
                      (a.summary?.return_pct ?? 0)
                  )
                  .map((r) => {
                    const ret = r.summary?.return_pct ?? 0;
                    return (
                      <tr
                        key={r.id}
                        className="border-t border-slate-800/60 hover:bg-slate-800/40"
                      >
                        <td className="max-w-[280px] truncate px-4 py-1.5 text-slate-300">
                          {r.label}
                        </td>
                        <td className="px-4 py-1.5 text-right text-slate-400">
                          {r.summary?.trades ?? 0}
                        </td>
                        <td className="px-4 py-1.5 text-right text-slate-400">
                          {(r.summary?.win_rate ?? 0).toFixed(1)}
                        </td>
                        <td
                          className={clsx(
                            "px-4 py-1.5 text-right",
                            ret > 0
                              ? "text-bull"
                              : ret < 0
                              ? "text-bear"
                              : "text-slate-400"
                          )}
                        >
                          {ret > 0 ? "+" : ""}
                          {ret.toFixed(2)}%
                        </td>
                        <td className="px-4 py-1.5 text-right text-slate-400">
                          {(r.summary?.max_drawdown_pct ?? 0).toFixed(2)}%
                        </td>
                        <td className="px-4 py-1.5 text-right text-slate-400">
                          {(r.summary?.profit_factor ?? 0) >= 999
                            ? "∞"
                            : (r.summary?.profit_factor ?? 0).toFixed(2)}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/** Best-effort type coercion per sweepable field. */
function coerce(key: keyof StrategyParams, raw: string): string | number | boolean {
  // Booleans
  if (key === "use_atr_sizing") {
    return /^(true|1|yes|on)$/i.test(raw);
  }
  // Strings
  if (key === "strategy" || key === "symbol" || key === "timeframe") {
    return raw;
  }
  // Otherwise numeric.
  const n = Number(raw);
  return Number.isFinite(n) ? n : raw;
}

function fmtDuration(s: SweepStatus): string {
  if (!s.started_at || !s.finished_at) return "—";
  return fmtSeconds(Math.round(s.finished_at - s.started_at));
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

/**
 * Compute a running ETA from the sweep status plus a "now" tick.
 * The backend only posts `completed` after each config finishes, so we
 * average time / completed config. If nothing has completed yet we still
 * expose elapsed so the user sees progress.
 */
function computeEta(
  status: SweepStatus | null,
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

/** Hook to poll /sweep/status while a sweep is running. */
export function useSweepPolling(
  fetcher: (signal?: AbortSignal) => Promise<SweepStatus>,
  intervalMs = 1500
): [SweepStatus | null, (s: SweepStatus) => void] {
  const [status, setStatus] = useState<SweepStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    // Initial fetch.
    fetcher(controller.signal)
      .then((s) => !cancelled && setStatus(s))
      .catch(() => {});

    const id = setInterval(async () => {
      try {
        const s = await fetcher();
        if (!cancelled) setStatus(s);
      } catch {
        /* ignore transient errors */
      }
    }, intervalMs);

    return () => {
      cancelled = true;
      controller.abort();
      clearInterval(id);
    };
  }, [fetcher, intervalMs]);

  return [status, setStatus];
}
