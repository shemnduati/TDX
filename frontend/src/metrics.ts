import type { DashboardData, EquityPoint, Trade } from "./types";

export interface Metrics {
  totalTrades: number;
  wins: number;
  losses: number;
  winRate: number;
  avgProfit: number;
  avgWin: number;
  avgLoss: number;
  totalPnL: number;
  totalReturnPct: number;
  maxDrawdown: number;
  maxDrawdownPct: number;
  bestTrade: number;
  worstTrade: number;
}

const EMPTY: Metrics = {
  totalTrades: 0,
  wins: 0,
  losses: 0,
  winRate: 0,
  avgProfit: 0,
  avgWin: 0,
  avgLoss: 0,
  totalPnL: 0,
  totalReturnPct: 0,
  maxDrawdown: 0,
  maxDrawdownPct: 0,
  bestTrade: 0,
  worstTrade: 0,
};

const mean = (xs: number[]) =>
  xs.length === 0 ? 0 : xs.reduce((a, b) => a + b, 0) / xs.length;

/**
 * Max drawdown = largest peak-to-trough drop on the equity curve.
 * Returned as both absolute value and percentage of the peak.
 */
function computeDrawdown(equity: EquityPoint[]): {
  maxDrawdown: number;
  maxDrawdownPct: number;
} {
  if (equity.length === 0) return { maxDrawdown: 0, maxDrawdownPct: 0 };

  let peak = equity[0].balance;
  let maxDd = 0;
  let maxDdPct = 0;

  for (const p of equity) {
    if (p.balance > peak) peak = p.balance;
    const dd = peak - p.balance;
    const ddPct = peak === 0 ? 0 : dd / peak;
    if (dd > maxDd) maxDd = dd;
    if (ddPct > maxDdPct) maxDdPct = ddPct;
  }

  return { maxDrawdown: maxDd, maxDrawdownPct: maxDdPct * 100 };
}

export function computeMetrics(data: DashboardData): Metrics {
  const trades: Trade[] = data.trades ?? [];
  if (trades.length === 0) {
    const { maxDrawdown, maxDrawdownPct } = computeDrawdown(
      data.equity_history ?? []
    );
    return { ...EMPTY, maxDrawdown, maxDrawdownPct };
  }

  const profits = trades.map((t) => t.profit);
  const wins = profits.filter((p) => p > 0);
  const losses = profits.filter((p) => p <= 0);

  const totalPnL = profits.reduce((a, b) => a + b, 0);
  const initial = data.initial_balance || 1;

  const { maxDrawdown, maxDrawdownPct } = computeDrawdown(
    data.equity_history ?? []
  );

  return {
    totalTrades: trades.length,
    wins: wins.length,
    losses: losses.length,
    winRate: (wins.length / trades.length) * 100,
    avgProfit: mean(profits),
    avgWin: mean(wins),
    avgLoss: mean(losses),
    totalPnL,
    totalReturnPct: (totalPnL / initial) * 100,
    maxDrawdown,
    maxDrawdownPct,
    bestTrade: Math.max(...profits),
    worstTrade: Math.min(...profits),
  };
}

export function formatCurrency(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

export function formatPct(n: number, digits = 2): string {
  return `${n.toFixed(digits)}%`;
}
