import type { DashboardData } from "../types";
import {
  computeMetrics,
  formatCurrency,
  formatPct,
} from "../metrics";
import { MetricCard } from "./MetricCard";

export function MetricsCards({ data }: { data: DashboardData }) {
  const m = computeMetrics(data);

  const pnlTone =
    m.totalPnL > 0 ? "positive" : m.totalPnL < 0 ? "negative" : "neutral";

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <MetricCard
        label="Balance"
        value={formatCurrency(data.balance)}
        sub={`Start: ${formatCurrency(data.initial_balance)}`}
      />
      <MetricCard
        label="Total P&L"
        value={formatCurrency(m.totalPnL)}
        sub={formatPct(m.totalReturnPct)}
        tone={pnlTone}
      />
      <MetricCard
        label="Win Rate"
        value={formatPct(m.winRate, 1)}
        sub={`${m.wins}W / ${m.losses}L`}
      />
      <MetricCard
        label="Avg Profit / Trade"
        value={formatCurrency(m.avgProfit)}
        sub={`${m.totalTrades} trades`}
        tone={m.avgProfit >= 0 ? "positive" : "negative"}
      />
      <MetricCard
        label="Max Drawdown"
        value={formatCurrency(m.maxDrawdown)}
        sub={formatPct(m.maxDrawdownPct)}
        tone={m.maxDrawdown > 0 ? "negative" : "neutral"}
      />
      <MetricCard
        label="Best / Worst"
        value={formatCurrency(m.bestTrade)}
        sub={`Worst ${formatCurrency(m.worstTrade)}`}
        tone="neutral"
      />
    </div>
  );
}
