import { clsx } from "clsx";
import type { Trade, TradeReason } from "../types";
import { formatCurrency } from "../metrics";

const REASON_LABELS: Record<string, string> = {
  signal: "Signal",
  reverse: "Reverse",
  stop_loss: "Stop",
  take_profit: "Target",
  backtest_end: "EOD",
};

const REASON_STYLES: Record<string, string> = {
  stop_loss: "bg-bear/10 text-bear",
  take_profit: "bg-bull/10 text-bull",
  reverse: "bg-amber-500/10 text-amber-300",
  signal: "bg-slate-800 text-slate-300",
  backtest_end: "bg-slate-800 text-slate-400",
};

function ReasonBadge({ reason }: { reason?: TradeReason }) {
  if (!reason) return <span className="text-slate-500">—</span>;
  return (
    <span
      className={clsx(
        "rounded px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider",
        REASON_STYLES[reason] ?? "bg-slate-800 text-slate-300"
      )}
    >
      {REASON_LABELS[reason] ?? reason}
    </span>
  );
}

function SideBadge({ side }: { side?: Trade["side"] }) {
  if (!side) return <span className="text-slate-500">—</span>;
  return (
    <span
      className={clsx(
        "rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
        side === "LONG" ? "bg-bull/10 text-bull" : "bg-bear/10 text-bear"
      )}
    >
      {side}
    </span>
  );
}

export function TradeTable({ trades }: { trades: Trade[] }) {
  const rows = [...trades].reverse();

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="flex items-center justify-between px-4 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Trade History
        </h2>
        <span className="text-xs text-slate-500">{trades.length} total</span>
      </div>

      <div className="max-h-96 overflow-auto">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-slate-900/90 text-xs uppercase tracking-wider text-slate-500 backdrop-blur">
            <tr>
              <th className="px-4 py-2 font-medium">#</th>
              <th className="px-4 py-2 font-medium">Closed</th>
              <th className="px-4 py-2 font-medium">Side</th>
              <th className="px-4 py-2 text-right font-medium">Entry</th>
              <th className="px-4 py-2 text-right font-medium">Exit</th>
              <th className="px-4 py-2 text-right font-medium">Size</th>
              <th className="px-4 py-2 text-right font-medium">P&L</th>
              <th className="px-4 py-2 font-medium">Reason</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={8}
                  className="px-4 py-8 text-center text-sm text-slate-500"
                >
                  No trades yet.
                </td>
              </tr>
            )}
            {rows.map((t, idx) => {
              const tradeNumber = trades.length - idx;
              const positive = t.profit > 0;
              const negative = t.profit < 0;
              return (
                <tr
                  key={`${t.timestamp ?? idx}-${tradeNumber}`}
                  className="border-t border-slate-800/60 hover:bg-slate-800/40"
                >
                  <td className="px-4 py-2 text-slate-500">{tradeNumber}</td>
                  <td className="px-4 py-2 text-slate-400">
                    {t.timestamp
                      ? new Date(t.timestamp).toLocaleString()
                      : "—"}
                  </td>
                  <td className="px-4 py-2">
                    <SideBadge side={t.side} />
                  </td>
                  <td className="px-4 py-2 text-right text-slate-300">
                    {formatCurrency(t.entry)}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-300">
                    {formatCurrency(t.exit)}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-400">
                    {t.size !== undefined ? t.size.toFixed(6) : "—"}
                  </td>
                  <td
                    className={clsx("px-4 py-2 text-right font-medium", {
                      "text-bull": positive,
                      "text-bear": negative,
                      "text-slate-400": !positive && !negative,
                    })}
                  >
                    {positive ? "+" : ""}
                    {formatCurrency(t.profit)}
                  </td>
                  <td className="px-4 py-2">
                    <ReasonBadge reason={t.reason} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
