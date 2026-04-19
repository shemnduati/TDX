import type { StrategyParams } from "../types";
import { enabledFilterSummaries } from "../runFilterSummary";

/** Current-tab callout: which generic filters were on and their values. */
export function OptInFiltersContext({
  params,
}: {
  params: StrategyParams | null | undefined;
}) {
  if (params == null) {
    return (
      <div className="rounded-lg border border-dashed border-slate-800 bg-slate-900/20 px-4 py-3 text-xs text-slate-500">
        No parameter snapshot is wired for this source. Open a saved run from
        History to see its filters here, or run a backtest with save on in this
        session so Latest backtest can show the same params.
      </div>
    );
  }

  const lines = enabledFilterSummaries(params);

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        Opt-in filters{" "}
        <span className="font-normal normal-case text-slate-600">
          (applied on top of the strategy)
        </span>
      </div>
      {lines.length === 0 ? (
        <p className="text-xs text-slate-500">
          None enabled — signals were only gated by the strategy itself.
        </p>
      ) : (
        <ul className="space-y-1.5 text-xs text-slate-300">
          {lines.map((line, i) => (
            <li key={i} className="flex gap-2 font-mono leading-snug">
              <span className="shrink-0 text-slate-600">•</span>
              <span>{line}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
