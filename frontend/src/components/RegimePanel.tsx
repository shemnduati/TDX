import { useMemo, useState } from "react";
import type { RegimeExpectancyResponse, StrategyParams } from "../types";

interface Props {
  params: StrategyParams | null;
  busy: boolean;
  data: RegimeExpectancyResponse | null;
  error: string | null;
  onRun: () => Promise<void>;
}

export function RegimePanel({ params, busy, data, error, onRun }: Props) {
  const [minTrades, setMinTrades] = useState(3);
  const byKey = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of data?.rows ?? []) {
      if (r.trades >= minTrades) {
        m.set(`${r.strategy}::${r.regime}`, r.expectancy_pct);
      }
    }
    return m;
  }, [data, minTrades]);

  const regimes = data?.regimes ?? [];
  const strategies = data?.strategies ?? [];

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
              Regime expectancy heatmap
            </h2>
            <p className="text-xs text-slate-500">
              3-axis regimes (trend x volatility x microstructure) from bar data,
              then per-strategy expectancy from replayed historical trades.
            </p>
          </div>
          <div className="flex items-end gap-2">
            <label className="text-xs text-slate-400">
              Min trades
              <input
                type="number"
                min={1}
                value={minTrades}
                onChange={(e) => setMinTrades(Math.max(1, Number(e.target.value) || 1))}
                className="ml-2 w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
              />
            </label>
            <button
              type="button"
              onClick={onRun}
              disabled={!params || busy}
              className="rounded-md bg-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "Computing..." : "Compute matrix"}
            </button>
          </div>
        </div>
        {params && (
          <p className="mt-2 text-xs text-slate-500">
            Using {params.symbol} · {params.timeframe} · {params.bars} bars.
          </p>
        )}
        {error && (
          <p className="mt-2 text-xs text-rose-300">{error}</p>
        )}
      </div>

      {data && (
        <div className="overflow-auto rounded-xl border border-slate-800 bg-slate-900/60 p-3">
          <table className="min-w-full border-collapse text-xs">
            <thead>
              <tr>
                <th className="sticky left-0 bg-slate-900 px-2 py-1 text-left text-slate-400">
                  Strategy
                </th>
                {regimes.map((r) => (
                  <th key={r} className="px-2 py-1 text-left text-slate-400">
                    {r}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {strategies.map((s) => (
                <tr key={s} className="border-t border-slate-800">
                  <td className="sticky left-0 bg-slate-900 px-2 py-1 font-mono text-slate-300">
                    {s}
                  </td>
                  {regimes.map((r) => {
                    const v = byKey.get(`${s}::${r}`);
                    return (
                      <td
                        key={`${s}:${r}`}
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
      )}
    </div>
  );
}
