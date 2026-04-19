import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EquityPoint } from "../types";
import { formatCurrency } from "../metrics";

interface Props {
  equity: EquityPoint[];
  initialBalance: number;
}

function formatTime(ts: string) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

interface ChartRow {
  time: string;
  balance: number;
  realizedPoint: number | null;
}

export function EquityCurveChart({ equity, initialBalance }: Props) {
  const data: ChartRow[] = equity.map((p) => ({
    time: formatTime(p.timestamp),
    balance: p.balance,
    realizedPoint: p.realized ? p.balance : null,
  }));

  const hasData = data.length > 1;
  const realizedCount = equity.filter((p) => p.realized).length;

  return (
    <div className="h-80 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Equity Curve
        </h2>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <LegendDot colorClass="bg-bull" label="Mark-to-market" />
          <LegendDot colorClass="bg-amber-400" label={`Realized (${realizedCount})`} />
        </div>
      </div>

      {hasData ? (
        <ResponsiveContainer width="100%" height="90%">
          <ComposedChart
            data={data}
            margin={{ top: 10, right: 16, left: 0, bottom: 0 }}
          >
            <defs>
              <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#10b981" stopOpacity={0.45} />
                <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis
              dataKey="time"
              stroke="#64748b"
              tick={{ fontSize: 11 }}
              minTickGap={24}
            />
            <YAxis
              stroke="#64748b"
              tick={{ fontSize: 11 }}
              domain={["auto", "auto"]}
              tickFormatter={(v) => formatCurrency(Number(v))}
              width={80}
            />
            <Tooltip
              contentStyle={{
                background: "#0f172a",
                border: "1px solid #1e293b",
                borderRadius: 8,
                color: "#e2e8f0",
              }}
              labelStyle={{ color: "#94a3b8" }}
              formatter={(value, name) => {
                if (value === null || value === undefined) return ["—", name];
                const n = Number(value);
                if (Number.isNaN(n)) return [String(value), name];
                return [formatCurrency(n), name];
              }}
            />
            <ReferenceLine
              y={initialBalance}
              stroke="#475569"
              strokeDasharray="4 4"
              label={{
                value: "Start",
                position: "insideTopRight",
                fill: "#64748b",
                fontSize: 11,
              }}
            />
            <Area
              type="monotone"
              dataKey="balance"
              name="Equity"
              stroke="transparent"
              fill="url(#equityFill)"
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="balance"
              name="Equity"
              stroke="#10b981"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Scatter
              dataKey="realizedPoint"
              name="Realized"
              fill="#f59e0b"
              shape="circle"
            />
          </ComposedChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-[85%] items-center justify-center text-sm text-slate-500">
          Waiting for ticks to build equity curve…
        </div>
      )}
    </div>
  );
}

function LegendDot({
  colorClass,
  label,
}: {
  colorClass: string;
  label: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block h-2 w-2 rounded-full ${colorClass}`} />
      {label}
    </span>
  );
}
