import { useMemo, useState } from "react";
import type {
  RegimeExpectancyResponse,
  SessionExpectancyResponse,
  StrategyParams,
} from "../types";

type View = "regime" | "session";

interface Props {
  params: StrategyParams | null;
  busy: boolean;
  data: RegimeExpectancyResponse | null;
  sessionData: SessionExpectancyResponse | null;
  error: string | null;
  onRun: () => Promise<void>;
  onRunSession: (weekendSplit: boolean) => Promise<void>;
}

function HeatmapTable({
  strategies,
  columns,
  rowKey,
  getValue,
}: {
  strategies: string[];
  columns: string[];
  rowKey: string;
  getValue: (strategy: string, col: string) => number | null;
}) {
  return (
    <div className="overflow-auto rounded-xl border border-slate-800 bg-slate-900/60 p-3">
      <table className="min-w-full border-collapse text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 bg-slate-900 px-2 py-1 text-left text-slate-400">
              Strategy
            </th>
            {columns.map((c) => (
              <th key={c} className="px-2 py-1 text-left text-slate-400 whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {strategies.map((s) => (
            <tr key={`${rowKey}-${s}`} className="border-t border-slate-800">
              <td className="sticky left-0 bg-slate-900 px-2 py-1 font-mono text-slate-300 whitespace-nowrap">
                {s}
              </td>
              {columns.map((c) => {
                const v = getValue(s, c);
                return (
                  <td
                    key={`${s}:${c}`}
                    className={`px-2 py-1 font-mono ${
                      v == null
                        ? "text-slate-600"
                        : v > 0
                        ? "text-emerald-300"
                        : v < 0
                        ? "text-rose-300"
                        : "text-slate-300"
                    }`}
                  >
                    {v == null ? "—" : `${v.toFixed(3)}%`}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RegimePanel({
  params,
  busy,
  data,
  sessionData,
  error,
  onRun,
  onRunSession,
}: Props) {
  const [minTrades, setMinTrades] = useState(3);
  const [view, setView] = useState<View>("regime");
  const [weekendSplit, setWeekendSplit] = useState(false);

  // --- Regime heatmap ---
  const regimeMap = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of data?.rows ?? []) {
      if (r.trades >= minTrades) {
        m.set(`${r.strategy}::${r.regime}`, r.expectancy_pct);
      }
    }
    return m;
  }, [data, minTrades]);

  // --- Session heatmap ---
  const sessionMap = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of sessionData?.rows ?? []) {
      if (r.trades >= minTrades) {
        m.set(`${r.strategy}::${r.session}`, r.expectancy_pct);
      }
    }
    return m;
  }, [sessionData, minTrades]);

  const SESSION_ORDER = ["asia", "london", "overlap", "ny", "off"];

  const sortedSessions = useMemo(() => {
    const raw = sessionData?.sessions ?? [];
    if (!weekendSplit) {
      return [...SESSION_ORDER].filter((s) => raw.includes(s));
    }
    const out: string[] = [];
    for (const s of SESSION_ORDER) {
      if (raw.includes(`${s}|weekday`)) out.push(`${s}|weekday`);
      if (raw.includes(`${s}|weekend`)) out.push(`${s}|weekend`);
    }
    const extra = raw.filter((s) => !out.includes(s));
    return [...out, ...extra];
  }, [sessionData, weekendSplit]);

  const handleRunSession = () => onRunSession(weekendSplit);

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        {/* Header row */}
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
              {view === "regime" ? "Regime expectancy heatmap" : "Session expectancy heatmap"}
            </h2>
            <p className="text-xs text-slate-500">
              {view === "regime"
                ? "3-axis regimes (trend × vol × microstructure) from bar data, per-strategy expectancy from replayed trades."
                : "UTC session buckets (asia · london · overlap · ny · off), per-strategy expectancy from replayed trades."}
            </p>
          </div>

          {/* View toggle */}
          <div className="flex rounded-md border border-slate-700 text-xs overflow-hidden">
            {(["regime", "session"] as View[]).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                className={`px-3 py-1.5 capitalize ${
                  view === v
                    ? "bg-slate-700 text-slate-100"
                    : "text-slate-400 hover:bg-slate-800"
                }`}
              >
                {v}
              </button>
            ))}
          </div>
        </div>

        {/* Controls row */}
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="text-xs text-slate-400">
            Min trades
            <input
              type="number"
              min={1}
              value={minTrades}
              onChange={(e) =>
                setMinTrades(Math.max(1, Number(e.target.value) || 1))
              }
              className="ml-2 w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
            />
          </label>

          {view === "session" && (
            <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
              <input
                type="checkbox"
                checked={weekendSplit}
                onChange={(e) => setWeekendSplit(e.target.checked)}
                className="rounded border-slate-600"
              />
              Weekend split
            </label>
          )}

          <button
            type="button"
            onClick={view === "regime" ? onRun : handleRunSession}
            disabled={!params || busy}
            className="rounded-md bg-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Computing..." : "Compute matrix"}
          </button>
        </div>

        {params && (
          <p className="mt-2 text-xs text-slate-500">
            Using {params.symbol} · {params.timeframe} · {params.bars} bars.
          </p>
        )}
        {error && <p className="mt-2 text-xs text-rose-300">{error}</p>}
      </div>

      {/* Regime heatmap */}
      {view === "regime" && data && (
        <HeatmapTable
          strategies={data.strategies}
          columns={data.regimes}
          rowKey="regime"
          getValue={(s, r) => regimeMap.get(`${s}::${r}`) ?? null}
        />
      )}

      {/* Session heatmap */}
      {view === "session" && sessionData && (
        <HeatmapTable
          strategies={sessionData.strategies}
          columns={sortedSessions}
          rowKey="session"
          getValue={(s, c) => sessionMap.get(`${s}::${c}`) ?? null}
        />
      )}
    </div>
  );
}
