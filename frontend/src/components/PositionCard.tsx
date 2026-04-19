import { clsx } from "clsx";
import type { DashboardData } from "../types";
import { formatCurrency } from "../metrics";

function latestUnrealized(data: DashboardData): number | null {
  if (!data.position) return null;
  const h = data.equity_history;
  if (!h || h.length === 0) return null;
  const last = h[h.length - 1];
  if (last.realized) return null;
  return last.balance - data.balance;
}

export function PositionCard({ data }: { data: DashboardData }) {
  const isOpen = data.position !== null;
  const unrealized = latestUnrealized(data);
  const unrealizedTone =
    unrealized === null
      ? "text-slate-400"
      : unrealized > 0
      ? "text-bull"
      : unrealized < 0
      ? "text-bear"
      : "text-slate-200";

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Open Position
        </h2>
        <span
          className={clsx(
            "rounded-full px-2 py-0.5 text-xs font-medium",
            isOpen ? "bg-bull/10 text-bull" : "bg-slate-800 text-slate-400"
          )}
        >
          {isOpen ? data.position : "FLAT"}
        </span>
      </div>

      <div className="mt-4 space-y-2 font-mono text-sm">
        <Row label="Side" value={data.position ?? "—"} />
        <Row
          label="Entry price"
          value={data.entry_price > 0 ? formatCurrency(data.entry_price) : "—"}
        />
        <Row
          label="Unrealized P&L"
          value={unrealized === null ? "—" : formatCurrency(unrealized)}
          valueClass={unrealizedTone}
        />
        <Row
          label="Last update"
          value={
            data.updated_at ? new Date(data.updated_at).toLocaleString() : "—"
          }
        />
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  valueClass = "text-slate-200",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-slate-500">{label}</span>
      <span className={valueClass}>{value}</span>
    </div>
  );
}
