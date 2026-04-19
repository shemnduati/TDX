import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RunPayload } from "../types";

/** Six-color palette for overlay series. Cycles on >6. */
const PALETTE = [
  "#60a5fa", // blue-400
  "#f59e0b", // amber-500
  "#10b981", // emerald-500
  "#f472b6", // pink-400
  "#a855f7", // purple-500
  "#ef4444", // red-500
];

interface Props {
  runs: RunPayload[];
}

interface SeriesRow {
  /** Fractional index along the run's own history (0..1). */
  t: number;
  [runId: string]: number;
}

export function EquityOverlayChart({ runs }: Props) {
  if (runs.length === 0) {
    return (
      <div className="flex h-80 items-center justify-center rounded-xl border border-dashed border-slate-800 bg-slate-900/40 text-sm text-slate-500">
        Select runs from History to compare their equity curves.
      </div>
    );
  }

  // Normalize every run to a 0..1 progression on the X axis and to % return
  // on the Y axis. This makes runs with different bar counts, symbols, and
  // time windows directly comparable.
  const RESOLUTION = 200;
  const buckets: SeriesRow[] = Array.from({ length: RESOLUTION + 1 }, (_, i) => ({
    t: i / RESOLUTION,
  }));

  const series = runs.map((run, idx) => {
    const history = run.data.equity_history ?? [];
    const initial = run.data.initial_balance || 1;
    const color = PALETTE[idx % PALETTE.length];
    const id = run.meta.id;

    if (history.length === 0) {
      return { id, label: run.meta.label, color };
    }

    // Sample the run's equity history at RESOLUTION+1 evenly-spaced indexes.
    for (let i = 0; i <= RESOLUTION; i++) {
      const pos = (history.length - 1) * (i / RESOLUTION);
      const lo = Math.floor(pos);
      const hi = Math.min(history.length - 1, lo + 1);
      const frac = pos - lo;
      const balance =
        history[lo].balance * (1 - frac) + history[hi].balance * frac;
      const returnPct = ((balance - initial) / initial) * 100;
      buckets[i][id] = returnPct;
    }

    return { id, label: run.meta.label, color };
  });

  return (
    <div className="h-96 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Equity comparison
        </h2>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          {series.map((s) => (
            <span key={s.id} className="inline-flex items-center gap-1.5 text-slate-400">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: s.color }}
              />
              <span className="max-w-[220px] truncate" title={s.label}>
                {s.label}
              </span>
            </span>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height="88%">
        <LineChart
          data={buckets}
          margin={{ top: 10, right: 16, left: 0, bottom: 0 }}
        >
          <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
          <XAxis
            dataKey="t"
            type="number"
            domain={[0, 1]}
            stroke="#64748b"
            tick={{ fontSize: 11 }}
            tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`}
            label={{
              value: "progress through run",
              position: "insideBottom",
              offset: -4,
              fill: "#64748b",
              fontSize: 10,
            }}
          />
          <YAxis
            stroke="#64748b"
            tick={{ fontSize: 11 }}
            domain={["auto", "auto"]}
            tickFormatter={(v) => `${Number(v).toFixed(0)}%`}
            width={60}
          />
          <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 4" />
          <Tooltip
            contentStyle={{
              background: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: 8,
              color: "#e2e8f0",
            }}
            labelStyle={{ color: "#94a3b8" }}
            labelFormatter={(v) => `t=${Math.round(Number(v) * 100)}%`}
            formatter={(value, name) => {
              const s = series.find((x) => x.id === name);
              const n = Number(value);
              if (Number.isNaN(n)) return ["—", s?.label ?? String(name)];
              return [`${n.toFixed(2)}%`, s?.label ?? String(name)];
            }}
          />
          {series.map((s) => (
            <Line
              key={s.id}
              dataKey={s.id}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls
              name={s.id}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
