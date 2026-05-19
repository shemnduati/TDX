import { clsx } from "clsx";
import type { RunMeta } from "../types";
import { formatCurrency } from "../metrics";
import { enabledFilterSummaries } from "../runFilterSummary";

interface Props {
  runs: RunMeta[];
  activeId?: string | null;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, label: string) => void;
  /** If provided, shows a "Clone" action per row that loads the run's
   * params into the Backtest form. */
  onClone?: (run: RunMeta) => void;
  /** If provided, shows a "Save as profile" action per row that
   * persists the run's params as a named profile. The prompt uses a
   * default name derived from the run label. */
  onSaveAsProfile?: (
    run: RunMeta,
    name: string,
    description: string
  ) => void;
  loading?: boolean;
  /** If provided, show a checkbox column for multi-select. */
  selectedIds?: Set<string>;
  onToggleSelected?: (id: string) => void;
}

export function RunList({
  runs,
  activeId,
  onOpen,
  onDelete,
  onRename,
  onClone,
  onSaveAsProfile,
  loading,
  selectedIds,
  onToggleSelected,
}: Props) {
  const selectable = !!selectedIds && !!onToggleSelected;
  if (loading) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-8 text-center text-sm text-slate-500">
        Loading runs…
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-800 bg-slate-900/40 p-8 text-center text-sm text-slate-500">
        No saved runs yet. Run a backtest or start a live session.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/40">
      <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="sticky top-0 bg-slate-900/90 text-xs uppercase tracking-wider text-slate-500 backdrop-blur">
          <tr>
            {selectable && <th className="w-8 px-2 py-2" />}
            <th className="px-4 py-2 font-medium">Label</th>
            <th className="px-4 py-2 font-medium">Kind</th>
            <th className="px-4 py-2 font-medium">Strategy</th>
            <th className="px-4 py-2 font-medium">Market</th>
            <th className="px-4 py-2 font-medium">Filters</th>
            <th className="px-4 py-2 text-right font-medium">Trades</th>
            <th className="px-4 py-2 text-right font-medium">Return</th>
            <th className="px-4 py-2 text-right font-medium">Balance</th>
            <th className="px-4 py-2 font-medium">Created</th>
            <th className="px-4 py-2 font-medium" />
          </tr>
        </thead>
        <tbody className="font-mono">
          {runs.map((run) => {
            const active = run.id === activeId;
            const selected = selectable && selectedIds!.has(run.id);
            const ret = run.summary?.return_pct ?? 0;
            const pos = ret > 0;
            const neg = ret < 0;
            const filterLines = enabledFilterSummaries(run.params);
            return (
              <tr
                key={run.id}
                className={clsx(
                  "border-t border-slate-800/60 transition-colors",
                  active && "bg-slate-800/60",
                  !active && selected && "bg-slate-800/30",
                  !active && !selected && "hover:bg-slate-800/40"
                )}
              >
                {selectable && (
                  <td className="px-2 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => onToggleSelected!(run.id)}
                      className="h-4 w-4 cursor-pointer rounded border-slate-700 bg-slate-950 text-slate-400 focus:ring-1 focus:ring-slate-500"
                    />
                  </td>
                )}
                <td className="px-4 py-2">
                  <button
                    type="button"
                    className="text-left text-slate-200 hover:underline"
                    onClick={() => onOpen(run.id)}
                  >
                    {run.label}
                  </button>
                </td>
                <td className="px-4 py-2">
                  <KindBadge kind={run.kind} />
                </td>
                <td className="px-4 py-2 text-slate-400">
                  <div className="flex items-center gap-2">
                    <span>{run.params?.strategy ?? "—"}</span>
                    {run.params?.use_atr_sizing && (
                      <span
                        className="rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-amber-300"
                        title="ATR-based position sizing"
                      >
                        ATR
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2 text-slate-400">
                  {run.params?.symbol} · {run.params?.timeframe}
                </td>
                <td
                  className="max-w-[13rem] px-4 py-2 align-top text-[10px] leading-snug text-slate-400"
                  title={filterLines.join(" · ") || "No opt-in filters enabled"}
                >
                  {filterLines.length === 0 ? (
                    <span className="text-slate-600">—</span>
                  ) : (
                    <ul className="list-none space-y-0.5 font-sans">
                      {filterLines.map((line, i) => (
                        <li key={i}>{line}</li>
                      ))}
                    </ul>
                  )}
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {run.summary?.trades ?? 0}
                </td>
                <td
                  className={clsx(
                    "px-4 py-2 text-right font-medium",
                    pos && "text-bull",
                    neg && "text-bear",
                    !pos && !neg && "text-slate-400"
                  )}
                >
                  {ret > 0 ? "+" : ""}
                  {ret.toFixed(2)}%
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {formatCurrency(run.summary?.balance ?? 0)}
                </td>
                <td className="px-4 py-2 text-slate-500">
                  {new Date(run.created_at).toLocaleString()}
                </td>
                <td className="whitespace-nowrap px-4 py-2">
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    {onClone && run.kind !== "portfolio" && (
                      <button
                        type="button"
                        className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800"
                        onClick={() => onClone(run)}
                        title="Load this run's params into the Backtest form"
                      >
                        Clone
                      </button>
                    )}
                    {onSaveAsProfile && run.kind !== "portfolio" && (
                      <button
                        type="button"
                        className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800"
                        title="Save this run's params as a named profile"
                        onClick={() => {
                          const suggested = toProfileName(
                            run.params?.symbol,
                            run.params?.timeframe,
                            run.params?.strategy
                          );
                          const name = window.prompt(
                            "Save as profile — profile name:",
                            suggested
                          );
                          if (!name || !name.trim()) return;
                          if (!NAME_RE.test(name.trim())) {
                            window.alert(
                              "Invalid profile name. Use letters, numbers, dots, dashes, underscores only (64 chars max)."
                            );
                            return;
                          }
                          const desc =
                            window.prompt(
                              "Description (optional):",
                              `From run ${run.label}`
                            ) ?? "";
                          onSaveAsProfile(run, name.trim(), desc);
                        }}
                      >
                        Save as profile
                      </button>
                    )}
                    <button
                      type="button"
                      className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800"
                      onClick={() => {
                        const next = window.prompt("Rename run", run.label);
                        if (next && next.trim() && next !== run.label) {
                          onRename(run.id, next.trim());
                        }
                      }}
                    >
                      Rename
                    </button>
                    <button
                      type="button"
                      className="rounded-md border border-bear/40 px-2 py-1 text-[10px] text-bear hover:bg-bear/10"
                      onClick={() => {
                        if (window.confirm(`Delete "${run.label}"?`)) {
                          onDelete(run.id);
                        }
                      }}
                    >
                      Delete
                    </button>
                  </div>
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

// Same character set as the backend profile-name regex in profiles.py.
const NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$/;

/** Build a reasonable default profile name from a run's market info.
 *  Turns e.g. ("ETH/USDT", "1h", "donchian_breakout") into
 *  "eth-1h-donchian-breakout". Falls back to "profile" if the inputs
 *  don't produce any usable slug (extremely rare — runs always have
 *  symbol/timeframe), so the prompt always has a sensible default. */
function toProfileName(
  symbol?: string,
  timeframe?: string,
  strategy?: string
): string {
  const parts = [
    symbol?.split("/")[0],
    timeframe,
    strategy?.replace(/_/g, "-"),
  ]
    .filter((x): x is string => !!x)
    .map((x) => x.toLowerCase())
    .map((x) => x.replace(/[^a-z0-9.\-_]/g, ""));
  const joined = parts.filter(Boolean).join("-");
  return joined || "profile";
}

function KindBadge({ kind }: { kind: "backtest" | "live" | "portfolio" }) {
  return (
    <span
      className={clsx(
        "rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wider",
        kind === "live"
          ? "bg-bull/15 text-bull"
          : kind === "portfolio"
          ? "bg-violet-500/15 text-violet-300"
          : "bg-slate-700/50 text-slate-300"
      )}
    >
      {kind}
    </span>
  );
}
