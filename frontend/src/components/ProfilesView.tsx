import { clsx } from "clsx";
import { useEffect, useMemo, useState } from "react";
import type {
  ProfileChangelogEntry,
  ProfileDoc,
  ProfileMeta,
  ProfilePerformancePreview,
  ProfilesWalkforwardRebaselineStart,
  ProfilesWalkforwardRebaselineResponse,
  StrategyParams,
} from "../types";

/**
 * Dedicated "Profiles" tab.
 *
 * Layout: a sortable list on the left and a full detail pane on the
 * right. The detail pane owns the per-profile actions (load, new
 * version, edit description, append changelog, delete). The list only
 * needs the lightweight `ProfileMeta`; the detail pane fetches the
 * full doc on demand via `onLoadFull`.
 */

interface Props {
  profiles: ProfileMeta[];
  loading?: boolean;
  onRefresh: () => void;
  /** Fetch the full document (with params + changelog + performance). */
  onLoadFull: (name: string) => Promise<ProfileDoc>;
  /** Copy the selected profile's params into the Backtest form and
   *  jump to that tab. */
  onLoadIntoBacktest: (doc: ProfileDoc) => void;
  /** Create a new child profile. Parent wiring is done by the caller;
   *  the form here just collects the user inputs. */
  onCreateVersion: (input: {
    name: string;
    description: string;
    changelogMessage: string;
    parent: string;
    fromDoc: ProfileDoc;
  }) => Promise<void>;
  /** Edit description in place. */
  onEditDescription: (name: string, description: string) => Promise<void>;
  /** Append a single changelog entry to an existing profile. */
  onAppendChangelog: (name: string, message: string) => Promise<void>;
  onDelete: (name: string) => Promise<void>;
  onRebaselineWalkforward: (
    body: ProfilesWalkforwardRebaselineStart
  ) => Promise<ProfilesWalkforwardRebaselineResponse>;
}

type SortKey = "name" | "created_at" | "return_pct" | "versions";

export function ProfilesView({
  profiles,
  loading,
  onRefresh,
  onLoadFull,
  onLoadIntoBacktest,
  onCreateVersion,
  onEditDescription,
  onAppendChangelog,
  onDelete,
  onRebaselineWalkforward,
}: Props) {
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [fullDoc, setFullDoc] = useState<ProfileDoc | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [filter, setFilter] = useState("");
  const [rebaselineBusy, setRebaselineBusy] = useState(false);
  const [rebaselineMsg, setRebaselineMsg] = useState<string | null>(null);
  const [rebaselineResult, setRebaselineResult] =
    useState<ProfilesWalkforwardRebaselineResponse | null>(null);
  const [showRebaselineOptions, setShowRebaselineOptions] = useState(false);
  const [rbTrainBars, setRbTrainBars] = useState(500);
  const [rbTestBars, setRbTestBars] = useState(200);
  const [rbStep, setRbStep] = useState<number | "">("");
  const [rbMcSims, setRbMcSims] = useState(2000);
  const [rbEngine, setRbEngine] = useState<"grid" | "optuna">("grid");
  const [rbOptunaTrials, setRbOptunaTrials] = useState(64);
  const [rbOptunaSeed, setRbOptunaSeed] = useState(42);
  const [rbMessage, setRbMessage] = useState(
    "rebaseline performance with walk-forward + final holdout OOS"
  );

  // Auto-select the first profile on first render so the detail pane
  // isn't empty when the tab opens.
  useEffect(() => {
    if (!selectedName && profiles.length > 0) {
      setSelectedName(profiles[0].name);
    } else if (
      selectedName &&
      !profiles.some((p) => p.name === selectedName)
    ) {
      // Currently-selected profile was deleted elsewhere.
      setSelectedName(profiles[0]?.name ?? null);
    }
  }, [profiles, selectedName]);

  // Refetch the full doc whenever selection changes. Keeping it fresh
  // matters because PATCH/POST operations elsewhere in the tab mutate
  // the same document.
  useEffect(() => {
    if (!selectedName) {
      setFullDoc(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    onLoadFull(selectedName)
      .then((doc) => {
        if (!cancelled) setFullDoc(doc);
      })
      .catch((e) => {
        if (!cancelled)
          setDetailError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedName, onLoadFull, profiles]);

  const sorted = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const filtered = q
      ? profiles.filter(
          (p) =>
            p.name.toLowerCase().includes(q) ||
            (p.description || "").toLowerCase().includes(q) ||
            (p.parent || "").toLowerCase().includes(q)
        )
      : profiles;
    const copy = [...filtered];
    copy.sort((a, b) => {
      switch (sortKey) {
        case "created_at":
          return (
            (b.created_at || "").localeCompare(a.created_at || "") ||
            a.name.localeCompare(b.name)
          );
        case "return_pct":
          return (
            (b.performance_preview?.return_pct ?? -Infinity) -
              (a.performance_preview?.return_pct ?? -Infinity) ||
            a.name.localeCompare(b.name)
          );
        case "versions":
          return (
            (b.version_count || 0) - (a.version_count || 0) ||
            a.name.localeCompare(b.name)
          );
        case "name":
        default:
          return a.name.localeCompare(b.name);
      }
    });
    return copy;
  }, [profiles, sortKey, filter]);

  if (loading && profiles.length === 0) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-12 text-center text-sm text-slate-500">
        Loading profiles…
      </div>
    );
  }

  if (profiles.length === 0) {
    return (
      <EmptyState onRefresh={onRefresh} />
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(320px,420px)_1fr]">
      <ProfileListPane
        profiles={sorted}
        selectedName={selectedName}
        onSelect={setSelectedName}
        onRefresh={onRefresh}
        sortKey={sortKey}
        onSortChange={setSortKey}
        filter={filter}
        onFilterChange={setFilter}
        rebaselineBusy={rebaselineBusy}
        rebaselineMsg={rebaselineMsg}
        rebaselineResult={rebaselineResult}
        showRebaselineOptions={showRebaselineOptions}
        onToggleRebaselineOptions={() =>
          setShowRebaselineOptions((prev) => !prev)
        }
        rbTrainBars={rbTrainBars}
        onRbTrainBarsChange={setRbTrainBars}
        rbTestBars={rbTestBars}
        onRbTestBarsChange={setRbTestBars}
        rbStep={rbStep}
        onRbStepChange={setRbStep}
        rbMcSims={rbMcSims}
        onRbMcSimsChange={setRbMcSims}
        rbEngine={rbEngine}
        onRbEngineChange={setRbEngine}
        rbOptunaTrials={rbOptunaTrials}
        onRbOptunaTrialsChange={setRbOptunaTrials}
        rbOptunaSeed={rbOptunaSeed}
        onRbOptunaSeedChange={setRbOptunaSeed}
        rbMessage={rbMessage}
        onRbMessageChange={setRbMessage}
        onRebaselineAll={async () => {
          setRebaselineBusy(true);
          setRebaselineMsg(null);
          setRebaselineResult(null);
          try {
            const r = await onRebaselineWalkforward({
              dry_run: false,
              train_bars: Math.max(1, Math.floor(rbTrainBars)),
              test_bars: Math.max(1, Math.floor(rbTestBars)),
              step: rbStep === "" ? undefined : Math.max(1, Math.floor(rbStep)),
              mc_sims: Math.max(0, Math.floor(rbMcSims)),
              train_engine: rbEngine,
              optuna_trials: Math.max(1, Math.floor(rbOptunaTrials)),
              optuna_seed: Math.floor(rbOptunaSeed),
              append_message: rbMessage.trim(),
            });
            setRebaselineResult(r);
            setRebaselineMsg(
              `Rebaseline complete: ${r.ok}/${r.total} updated in ${r.elapsed_secs.toFixed(1)}s`
            );
            onRefresh();
          } catch (e) {
            setRebaselineMsg(
              `Rebaseline failed: ${e instanceof Error ? e.message : String(e)}`
            );
          } finally {
            setRebaselineBusy(false);
          }
        }}
        onRebaselineProfiles={async (names) => {
          if (!names.length) return;
          setRebaselineBusy(true);
          setRebaselineMsg(null);
          setRebaselineResult(null);
          try {
            const r = await onRebaselineWalkforward({
              profiles: names,
              dry_run: false,
              train_bars: Math.max(1, Math.floor(rbTrainBars)),
              test_bars: Math.max(1, Math.floor(rbTestBars)),
              step: rbStep === "" ? undefined : Math.max(1, Math.floor(rbStep)),
              mc_sims: Math.max(0, Math.floor(rbMcSims)),
              train_engine: rbEngine,
              optuna_trials: Math.max(1, Math.floor(rbOptunaTrials)),
              optuna_seed: Math.floor(rbOptunaSeed),
              append_message: rbMessage.trim(),
            });
            setRebaselineResult(r);
            setRebaselineMsg(
              `Re-run failed complete: ${r.ok}/${r.total} updated in ${r.elapsed_secs.toFixed(1)}s`
            );
            onRefresh();
          } catch (e) {
            setRebaselineMsg(
              `Re-run failed failed: ${e instanceof Error ? e.message : String(e)}`
            );
          } finally {
            setRebaselineBusy(false);
          }
        }}
        onDryRunSelected={async () => {
          if (!selectedName) return;
          setRebaselineBusy(true);
          setRebaselineMsg(null);
          setRebaselineResult(null);
          try {
            const r = await onRebaselineWalkforward({
              profiles: [selectedName],
              dry_run: true,
              train_bars: Math.max(1, Math.floor(rbTrainBars)),
              test_bars: Math.max(1, Math.floor(rbTestBars)),
              step: rbStep === "" ? undefined : Math.max(1, Math.floor(rbStep)),
              mc_sims: Math.max(0, Math.floor(rbMcSims)),
              train_engine: rbEngine,
              optuna_trials: Math.max(1, Math.floor(rbOptunaTrials)),
              optuna_seed: Math.floor(rbOptunaSeed),
            });
            setRebaselineResult(r);
            const row = r.rows[0];
            if (row?.ok && row.summary) {
              const mean = Number((row.summary as Record<string, unknown>).mean_test_ret ?? 0);
              const finalOos = Number(
                (row.summary as Record<string, unknown>).final_oos_return_pct ?? 0
              );
              setRebaselineMsg(
                `Dry-run ${selectedName}: WFO mean ${mean.toFixed(2)}%, final OOS ${finalOos.toFixed(2)}%`
              );
            } else {
              setRebaselineMsg(
                `Dry-run ${selectedName}: ${row?.error ?? "no result"}`
              );
            }
          } catch (e) {
            setRebaselineMsg(
              `Dry-run failed: ${e instanceof Error ? e.message : String(e)}`
            );
          } finally {
            setRebaselineBusy(false);
          }
        }}
      />

      <div>
        {detailLoading && !fullDoc ? (
          <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-8 text-center text-sm text-slate-500">
            Loading profile…
          </div>
        ) : detailError ? (
          <div className="rounded-lg border border-bear/40 bg-bear/10 p-4 text-sm text-bear">
            {detailError}
          </div>
        ) : fullDoc ? (
          <ProfileDetailPane
            doc={fullDoc}
            profiles={profiles}
            onLoadIntoBacktest={onLoadIntoBacktest}
            onCreateVersion={onCreateVersion}
            onEditDescription={onEditDescription}
            onAppendChangelog={onAppendChangelog}
            onDelete={onDelete}
            onSelectProfile={setSelectedName}
          />
        ) : null}
      </div>
    </div>
  );
}

// =====================================================================
// List pane
// =====================================================================

function ProfileListPane({
  profiles,
  selectedName,
  onSelect,
  onRefresh,
  sortKey,
  onSortChange,
  filter,
  onFilterChange,
  rebaselineBusy,
  rebaselineMsg,
  rebaselineResult,
  showRebaselineOptions,
  onToggleRebaselineOptions,
  rbTrainBars,
  onRbTrainBarsChange,
  rbTestBars,
  onRbTestBarsChange,
  rbStep,
  onRbStepChange,
  rbMcSims,
  onRbMcSimsChange,
  rbEngine,
  onRbEngineChange,
  rbOptunaTrials,
  onRbOptunaTrialsChange,
  rbOptunaSeed,
  onRbOptunaSeedChange,
  rbMessage,
  onRbMessageChange,
  onRebaselineAll,
  onRebaselineProfiles,
  onDryRunSelected,
}: {
  profiles: ProfileMeta[];
  selectedName: string | null;
  onSelect: (name: string) => void;
  onRefresh: () => void;
  sortKey: SortKey;
  onSortChange: (k: SortKey) => void;
  filter: string;
  onFilterChange: (s: string) => void;
  rebaselineBusy: boolean;
  rebaselineMsg: string | null;
  rebaselineResult: ProfilesWalkforwardRebaselineResponse | null;
  showRebaselineOptions: boolean;
  onToggleRebaselineOptions: () => void;
  rbTrainBars: number;
  onRbTrainBarsChange: (n: number) => void;
  rbTestBars: number;
  onRbTestBarsChange: (n: number) => void;
  rbStep: number | "";
  onRbStepChange: (n: number | "") => void;
  rbMcSims: number;
  onRbMcSimsChange: (n: number) => void;
  rbEngine: "grid" | "optuna";
  onRbEngineChange: (v: "grid" | "optuna") => void;
  rbOptunaTrials: number;
  onRbOptunaTrialsChange: (n: number) => void;
  rbOptunaSeed: number;
  onRbOptunaSeedChange: (n: number) => void;
  rbMessage: string;
  onRbMessageChange: (v: string) => void;
  onRebaselineAll: () => Promise<void>;
  onRebaselineProfiles: (names: string[]) => Promise<void>;
  onDryRunSelected: () => Promise<void>;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
      <div className="mb-3 flex items-center gap-2">
        <input
          type="text"
          placeholder="Filter by name / description / parent…"
          value={filter}
          onChange={(e) => onFilterChange(e.target.value)}
          className="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none"
        />
        <select
          value={sortKey}
          onChange={(e) => onSortChange(e.target.value as SortKey)}
          className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none"
          title="Sort profiles"
        >
          <option value="name">Sort: Name</option>
          <option value="created_at">Sort: Newest</option>
          <option value="return_pct">Sort: Return</option>
          <option value="versions">Sort: Versions</option>
        </select>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-md border border-slate-700 px-2 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
          title="Reload profiles from disk"
        >
          ↻
        </button>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void onRebaselineAll()}
          disabled={rebaselineBusy}
          className="rounded-md border border-indigo-500/40 px-2 py-1.5 text-[11px] text-indigo-200 hover:bg-indigo-500/10 disabled:cursor-not-allowed disabled:opacity-50"
          title="Refresh all profile performance baselines via walk-forward"
        >
          {rebaselineBusy ? "Rebaselining…" : "Rebaseline all (WFO)"}
        </button>
        <button
          type="button"
          onClick={() => void onDryRunSelected()}
          disabled={rebaselineBusy || !selectedName}
          className="rounded-md border border-slate-700 px-2 py-1.5 text-[11px] text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          title="Evaluate selected profile with WFO without writing to disk"
        >
          Dry-run selected
        </button>
        <button
          type="button"
          onClick={onToggleRebaselineOptions}
          className="rounded-md border border-slate-700 px-2 py-1.5 text-[11px] text-slate-300 hover:bg-slate-800"
          title="Tune walk-forward rebaseline parameters"
        >
          {showRebaselineOptions ? "Hide options" : "Options"}
        </button>
      </div>
      {showRebaselineOptions && (
        <div className="mb-3 rounded-md border border-slate-800 bg-slate-950/50 p-2">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <MiniNumberField
              label="Train bars"
              value={rbTrainBars}
              onChange={onRbTrainBarsChange}
            />
            <MiniNumberField
              label="Test bars"
              value={rbTestBars}
              onChange={onRbTestBarsChange}
            />
            <MiniNumberField
              label="Step (optional)"
              value={rbStep === "" ? 0 : rbStep}
              onChange={(v) => onRbStepChange(v <= 0 ? "" : v)}
            />
            <MiniNumberField
              label="MC sims"
              value={rbMcSims}
              onChange={onRbMcSimsChange}
            />
            <label className="block text-[10px] text-slate-400">
              Train engine
              <select
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200 focus:border-slate-500 focus:outline-none"
                value={rbEngine}
                onChange={(e) =>
                  onRbEngineChange(e.target.value === "optuna" ? "optuna" : "grid")
                }
              >
                <option value="grid">grid</option>
                <option value="optuna">optuna</option>
              </select>
            </label>
            <MiniNumberField
              label="Optuna trials"
              value={rbOptunaTrials}
              onChange={onRbOptunaTrialsChange}
            />
            <MiniNumberField
              label="Optuna seed"
              value={rbOptunaSeed}
              onChange={onRbOptunaSeedChange}
            />
            <label className="block text-[10px] text-slate-400 sm:col-span-2">
              Changelog append message
              <input
                value={rbMessage}
                onChange={(e) => onRbMessageChange(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200 focus:border-slate-500 focus:outline-none"
              />
            </label>
          </div>
        </div>
      )}
      {rebaselineMsg && (
        <div className="mb-3 rounded-md border border-slate-700 bg-slate-950/60 px-2 py-1.5 text-[11px] text-slate-300">
          {rebaselineMsg}
        </div>
      )}
      {rebaselineResult && (
        <RebaselineResultCard
          result={rebaselineResult}
          onRerunFailed={(names) => onRebaselineProfiles(names)}
        />
      )}
      <ul className="max-h-[72vh] space-y-1 overflow-auto pr-1">
        {profiles.map((p) => {
          const active = p.name === selectedName;
          return (
            <li key={p.name}>
              <button
                type="button"
                onClick={() => onSelect(p.name)}
                className={clsx(
                  "w-full rounded-md border p-2 text-left transition-colors",
                  active
                    ? "border-slate-500 bg-slate-800/60"
                    : "border-slate-800 bg-slate-950/50 hover:border-slate-700 hover:bg-slate-900"
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-slate-200">
                      {p.name}
                    </div>
                    <div className="truncate text-[10px] text-slate-500">
                      {[p.preview.symbol, p.preview.timeframe, p.preview.strategy]
                        .filter(Boolean)
                        .join(" · ") || "(matches defaults)"}
                    </div>
                  </div>
                  <PerformanceBadge perf={p.performance_preview} />
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5 text-[10px]">
                  {p.parent && (
                    <span
                      className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-400"
                      title={`Child of ${p.parent}`}
                    >
                      ← {p.parent}
                    </span>
                  )}
                  {p.version_count > 0 && (
                    <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-300">
                      {p.version_count} version
                      {p.version_count === 1 ? "" : "s"}
                    </span>
                  )}
                  {p.override_count > 0 && (
                    <span className="rounded bg-slate-800/60 px-1.5 py-0.5 text-slate-500">
                      {p.override_count} override
                      {p.override_count === 1 ? "" : "s"}
                    </span>
                  )}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function RebaselineResultCard({
  result,
  onRerunFailed,
}: {
  result: ProfilesWalkforwardRebaselineResponse;
  onRerunFailed: (names: string[]) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(true);
  const [failedOnly, setFailedOnly] = useState(false);
  const fails = result.rows.filter((r) => !r.ok);
  const visibleRows = failedOnly ? fails : result.rows;
  const downloadCsv = () => {
    const lines = [
      [
        "name",
        "ok",
        "error",
        "symbol",
        "timeframe",
        "strategy",
        "wfo_mean_test_ret_pct",
        "wfo_positive_rate_pct",
        "final_oos_return_pct",
        "final_oos_trades",
      ].join(","),
    ];
    for (const row of result.rows) {
      const s = (row.summary || {}) as Record<string, unknown>;
      lines.push(
        [
          csvCell(row.name),
          csvCell(String(!!row.ok)),
          csvCell(row.error ?? ""),
          csvCell(row.symbol ?? ""),
          csvCell(row.timeframe ?? ""),
          csvCell(row.strategy ?? ""),
          csvCell(String(Number(s.mean_test_ret ?? 0))),
          csvCell(String(Number(s.positive_rate ?? 0))),
          csvCell(String(Number(s.final_oos_return_pct ?? 0))),
          csvCell(String(Number(s.final_oos_trades ?? 0))),
        ].join(",")
      );
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    a.href = url;
    a.download = `profiles_wf_rebaseline_${stamp}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };
  const copyFailedNames = async () => {
    const names = fails.map((r) => r.name).filter(Boolean);
    if (!names.length) return;
    const text = names.join(",");
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
    } catch {
      // no-op: keep button best-effort only
    }
  };
  return (
    <div className="mb-3 rounded-md border border-slate-700 bg-slate-950/60">
      <div className="flex items-center justify-between px-2 py-1.5">
        <div className="text-[11px] text-slate-300">
          Last run: {result.ok}/{result.total} ok · {fails.length} failed ·{" "}
          {result.elapsed_secs.toFixed(1)}s
          {result.fallback_reason && (
            <>
              {" "}
              · engine {result.effective_engine ?? "grid"} (requested{" "}
              {result.requested_engine ?? "optuna"}, Optuna unavailable)
            </>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => void onRerunFailed(fails.map((r) => r.name))}
            disabled={fails.length === 0}
            className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Re-run failed
          </button>
          <button
            type="button"
            onClick={() => void copyFailedNames()}
            disabled={fails.length === 0}
            className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Copy failed names
          </button>
          <button
            type="button"
            onClick={downloadCsv}
            className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400 hover:bg-slate-800"
          >
            CSV
          </button>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400 hover:bg-slate-800"
          >
            {expanded ? "Hide rows" : "Show rows"}
          </button>
        </div>
      </div>
      {expanded && (
        <div className="max-h-56 overflow-auto border-t border-slate-800">
          <div className="flex items-center justify-between border-b border-slate-800 px-2 py-1">
            <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
              <input
                type="checkbox"
                checked={failedOnly}
                onChange={(e) => setFailedOnly(e.target.checked)}
              />
              Failed only
            </label>
            <span className="text-[10px] text-slate-500">
              showing {visibleRows.length}/{result.rows.length}
            </span>
          </div>
          <table className="min-w-full text-[10px]">
            <thead className="sticky top-0 bg-slate-900/90 text-slate-500">
              <tr>
                <th className="px-2 py-1 text-left font-medium">Profile</th>
                <th className="px-2 py-1 text-left font-medium">Status</th>
                <th className="px-2 py-1 text-right font-medium">WFO mean%</th>
                <th className="px-2 py-1 text-right font-medium">Final OOS%</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row) => {
                const s = (row.summary || {}) as Record<string, unknown>;
                const mean = Number(s.mean_test_ret ?? 0);
                const oos = Number(s.final_oos_return_pct ?? 0);
                return (
                  <tr key={row.name} className="border-t border-slate-800/60">
                    <td className="px-2 py-1 font-mono text-slate-300">
                      {row.name}
                    </td>
                    <td className={clsx("px-2 py-1", row.ok ? "text-bull" : "text-bear")}>
                      {row.ok ? "ok" : row.error || "error"}
                    </td>
                    <td className="px-2 py-1 text-right text-slate-300">
                      {row.ok ? `${mean > 0 ? "+" : ""}${mean.toFixed(2)}` : "—"}
                    </td>
                    <td className="px-2 py-1 text-right text-slate-300">
                      {row.ok ? `${oos > 0 ? "+" : ""}${oos.toFixed(2)}` : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function csvCell(v: string): string {
  const s = String(v ?? "");
  if (/[",\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function MiniNumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
}) {
  return (
    <label className="block text-[10px] text-slate-400">
      {label}
      <input
        type="number"
        min={0}
        value={value || ""}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200 focus:border-slate-500 focus:outline-none"
      />
    </label>
  );
}

function PerformanceBadge({
  perf,
}: {
  perf: ProfilePerformancePreview | null;
}) {
  if (!perf || perf.return_pct == null) {
    return (
      <span className="whitespace-nowrap rounded-md bg-slate-800/60 px-1.5 py-0.5 text-[10px] text-slate-500">
        no stats
      </span>
    );
  }
  const ret = perf.return_pct;
  return (
    <span
      className={clsx(
        "whitespace-nowrap rounded-md px-1.5 py-0.5 font-mono text-[10px]",
        ret > 0
          ? "bg-bull/10 text-bull"
          : ret < 0
          ? "bg-bear/10 text-bear"
          : "bg-slate-800/60 text-slate-400"
      )}
      title={`${perf.kind ?? "backtest"} · ${perf.trades ?? "?"} trades`}
    >
      {ret > 0 ? "+" : ""}
      {ret.toFixed(2)}%
    </span>
  );
}

// =====================================================================
// Detail pane
// =====================================================================

function ProfileDetailPane({
  doc,
  profiles,
  onLoadIntoBacktest,
  onCreateVersion,
  onEditDescription,
  onAppendChangelog,
  onDelete,
  onSelectProfile,
}: {
  doc: ProfileDoc;
  profiles: ProfileMeta[];
  onLoadIntoBacktest: (doc: ProfileDoc) => void;
  onCreateVersion: (input: {
    name: string;
    description: string;
    changelogMessage: string;
    parent: string;
    fromDoc: ProfileDoc;
  }) => Promise<void>;
  onEditDescription: (name: string, description: string) => Promise<void>;
  onAppendChangelog: (name: string, message: string) => Promise<void>;
  onDelete: (name: string) => Promise<void>;
  onSelectProfile: (name: string) => void;
}) {
  const lineage = useLineage(doc, profiles);
  const children = useMemo(
    () => profiles.filter((p) => p.parent === doc.name),
    [profiles, doc.name]
  );

  return (
    <div className="space-y-4">
      <HeaderCard
        doc={doc}
        lineage={lineage}
        onLoadIntoBacktest={() => onLoadIntoBacktest(doc)}
        onDelete={() => onDelete(doc.name)}
        onSelectProfile={onSelectProfile}
      />

      <NewVersionCard
        doc={doc}
        onCreate={(name, description, message) =>
          onCreateVersion({
            name,
            description,
            changelogMessage: message,
            parent: doc.name,
            fromDoc: doc,
          })
        }
      />

      <DescriptionCard
        doc={doc}
        onSave={(desc) => onEditDescription(doc.name, desc)}
      />

      <PerformanceCard doc={doc} />

      <ParamsCard doc={doc} />

      <ChangelogCard
        entries={doc.changelog}
        onAppend={(msg) => onAppendChangelog(doc.name, msg)}
      />

      {children.length > 0 && (
        <ChildrenCard
          children={children}
          onSelect={onSelectProfile}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------- header card ---

function HeaderCard({
  doc,
  lineage,
  onLoadIntoBacktest,
  onDelete,
  onSelectProfile,
}: {
  doc: ProfileDoc;
  lineage: ProfileMeta[];
  onLoadIntoBacktest: () => void;
  onDelete: () => void;
  onSelectProfile: (name: string) => void;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">{doc.name}</h2>
          <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-slate-500">
            {doc.created_at && (
              <span>created {formatDate(doc.created_at)}</span>
            )}
            {doc.source && <span>· source: {doc.source}</span>}
          </div>
          {lineage.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1 text-[10px] text-slate-400">
              <span className="text-slate-500">lineage:</span>
              {lineage.map((p, i) => (
                <span key={p.name} className="flex items-center gap-1">
                  {i > 0 && <span className="text-slate-600">→</span>}
                  <button
                    type="button"
                    onClick={() => onSelectProfile(p.name)}
                    className="rounded bg-slate-800/80 px-1.5 py-0.5 font-mono text-slate-300 hover:bg-slate-700"
                  >
                    {p.name}
                  </button>
                </span>
              ))}
              <span className="text-slate-600">→</span>
              <span className="rounded bg-slate-700 px-1.5 py-0.5 font-mono text-slate-200">
                {doc.name}
              </span>
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onLoadIntoBacktest}
            className="rounded-md bg-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-white"
          >
            Load into Backtest
          </button>
          <button
            type="button"
            onClick={() => {
              if (window.confirm(`Delete profile "${doc.name}"?`)) onDelete();
            }}
            className="rounded-md border border-bear/40 px-3 py-1.5 text-xs text-bear hover:bg-bear/10"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------- new version card ------

function NewVersionCard({
  doc,
  onCreate,
}: {
  doc: ProfileDoc;
  onCreate: (name: string, description: string, message: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(() => suggestNextName(doc.name));
  const [desc, setDesc] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    // Reset suggestion when a new profile is selected.
    setName(suggestNextName(doc.name));
    setDesc("");
    setMsg("");
    setErr(null);
    setOpen(false);
  }, [doc.name]);

  const valid = isValidName(name) && msg.trim().length > 0;

  const submit = async () => {
    if (!valid) return;
    setBusy(true);
    setErr(null);
    try {
      await onCreate(name.trim(), desc.trim(), msg.trim());
      setOpen(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-slate-200">
              Iterate on this profile
            </h3>
            <p className="text-[11px] text-slate-500">
              Creates a new profile with <code>parent = {doc.name}</code> so
              the chain of improvements stays recorded. Params come from
              this profile; change them in Backtest after loading, then
              Save-as the next version.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="shrink-0 rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800"
          >
            New version…
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">New version</h3>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="text-[10px] text-slate-500 hover:text-slate-300"
        >
          cancel
        </button>
      </div>
      <p className="mb-3 text-[11px] text-slate-500">
        This creates a child of <strong>{doc.name}</strong>. The child
        starts with the same params — you'll likely want to "Load into
        Backtest", tweak knobs, and then save from the run. For
        metadata-only iterations (notes, new stats on same params), use
        "Append changelog" below instead.
      </p>
      <div className="grid gap-2 md:grid-cols-2">
        <label className="text-[10px] text-slate-400">
          New profile name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="name-v2"
            className={clsx(
              "mt-1 w-full rounded-md border bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:outline-none",
              name && !isValidName(name)
                ? "border-bear/60 focus:border-bear"
                : "border-slate-700 focus:border-slate-500"
            )}
          />
        </label>
        <label className="text-[10px] text-slate-400">
          Short description (optional)
          <input
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder={`Version 2 of ${doc.name}`}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none"
          />
        </label>
        <label className="text-[10px] text-slate-400 md:col-span-2">
          What changed, and how did it improve performance? *
          <textarea
            value={msg}
            onChange={(e) => setMsg(e.target.value)}
            rows={3}
            placeholder="e.g. Enabled ADX filter (min=20). WF score 0.17 -> 0.30, positive-rate 60% -> 69%."
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none"
          />
        </label>
      </div>
      {name && !isValidName(name) && (
        <div className="mt-2 text-[10px] text-bear">
          Names must start with a letter/number and contain only letters,
          numbers, dots, dashes, or underscores (64 chars max).
        </div>
      )}
      {err && <div className="mt-2 text-[10px] text-bear">{err}</div>}
      <div className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={!valid || busy}
          className="rounded-md bg-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Saving…" : "Create version"}
        </button>
      </div>
    </div>
  );
}

// --------------------------------------------------- description card ----

function DescriptionCard({
  doc,
  onSave,
}: {
  doc: ProfileDoc;
  onSave: (description: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(doc.description);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setDraft(doc.description);
    setEditing(false);
  }, [doc.name, doc.description]);

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">Description</h3>
        {!editing ? (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="text-[10px] text-slate-400 hover:text-slate-200"
          >
            edit
          </button>
        ) : (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                setDraft(doc.description);
                setEditing(false);
              }}
              className="text-[10px] text-slate-500 hover:text-slate-300"
            >
              cancel
            </button>
            <button
              type="button"
              disabled={busy || draft === doc.description}
              onClick={async () => {
                setBusy(true);
                try {
                  await onSave(draft);
                  setEditing(false);
                } finally {
                  setBusy(false);
                }
              }}
              className="rounded-md bg-slate-200 px-2 py-0.5 text-[10px] font-semibold text-slate-950 hover:bg-white disabled:opacity-50"
            >
              {busy ? "…" : "save"}
            </button>
          </div>
        )}
      </div>
      {editing ? (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          className="w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none"
        />
      ) : (
        <p className="whitespace-pre-wrap text-xs text-slate-300">
          {doc.description || (
            <span className="text-slate-600">
              (no description yet — click edit)
            </span>
          )}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------- performance card ---

function PerformanceCard({ doc }: { doc: ProfileDoc }) {
  const perf = doc.performance;
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">
          Performance baseline
        </h3>
        {perf && (
          <span className="text-[10px] text-slate-500">
            {perf.kind ?? "backtest"}
            {perf.recorded_at && ` · recorded ${formatDate(perf.recorded_at)}`}
          </span>
        )}
      </div>
      {!perf || !perf.summary ? (
        <p className="text-[11px] text-slate-500">
          No performance recorded for this profile yet. Save a new version
          from a run, or attach a run from the Backtest tab using
          <em> Save as profile</em>, and the summary will appear here.
        </p>
      ) : (
        <>
          <SummaryGrid
            summary={perf.summary as Record<string, unknown>}
          />
          {perf.run_id && (
            <div className="mt-2 text-[10px] text-slate-500">
              run ref: <code className="text-slate-400">{perf.run_id}</code>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// A compact drop-in metrics grid; mirrors the Backtest view's
// SummaryTable but lives here so the profiles tab doesn't import App.tsx.
function SummaryGrid({ summary }: { summary: Record<string, unknown> }) {
  const order = [
    "trades",
    "win_rate",
    "return_pct",
    "profit_factor",
    "trade_sharpe",
    "max_drawdown_pct",
    "avg_trade_pnl",
    "total_pnl",
    "balance",
    "timeframe",
    "bars",
  ];
  const keys = order.filter((k) => k in summary);
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 font-mono text-xs sm:grid-cols-3">
      {keys.map((k) => (
        <div key={k} className="flex justify-between gap-2">
          <span className="text-slate-500">{k}</span>
          <span className={valueClass(k, summary[k])}>
            {formatSummaryValue(summary[k])}
          </span>
        </div>
      ))}
    </div>
  );
}

function valueClass(key: string, v: unknown): string {
  if (typeof v !== "number") return "text-slate-200";
  if (key === "return_pct" || key === "total_pnl" || key === "avg_trade_pnl") {
    if (v > 0) return "text-bull";
    if (v < 0) return "text-bear";
  }
  if (key === "max_drawdown_pct" && v < 0) return "text-bear";
  return "text-slate-200";
}

function formatSummaryValue(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") {
    if (Number.isInteger(v)) return v.toString();
    return v.toFixed(2);
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// ------------------------------------------------------- params card -----

function ParamsCard({ doc }: { doc: ProfileDoc }) {
  const entries = Object.entries(doc.params) as [
    keyof StrategyParams,
    unknown
  ][];
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">
          Parameter overrides
        </h3>
        <span className="text-[10px] text-slate-500">
          {entries.length} field{entries.length === 1 ? "" : "s"} differ from
          config.py defaults
        </span>
      </div>
      {entries.length === 0 ? (
        <p className="text-[11px] text-slate-500">
          This profile matches the current config.py defaults exactly.
          That's unusual — most useful profiles override at least the
          symbol and timeframe.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-x-6 gap-y-1 font-mono text-xs sm:grid-cols-2">
          {entries.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2 border-b border-slate-800/40 py-1">
              <span className="text-slate-500">{k}</span>
              <span className="text-slate-200">{JSON.stringify(v)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------- changelog card -----

function ChangelogCard({
  entries,
  onAppend,
}: {
  entries: ProfileChangelogEntry[];
  onAppend: (msg: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    const msg = draft.trim();
    if (!msg) return;
    setBusy(true);
    setErr(null);
    try {
      await onAppend(msg);
      setDraft("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h3 className="mb-2 text-sm font-semibold text-slate-200">
        Changelog
      </h3>
      {entries.length === 0 ? (
        <p className="mb-3 text-[11px] text-slate-500">
          No entries yet. Log notes whenever you change the description
          or attach new performance stats — the history stays with the
          profile forever.
        </p>
      ) : (
        <ol className="mb-3 space-y-2">
          {[...entries].reverse().map((e, i) => (
            <li
              key={`${e.at}-${i}`}
              className="rounded-md border border-slate-800 bg-slate-950/50 px-3 py-2"
            >
              <div className="text-[10px] text-slate-500">
                {formatDate(e.at)}
              </div>
              <div className="whitespace-pre-wrap text-xs text-slate-200">
                {e.message}
              </div>
            </li>
          ))}
        </ol>
      )}
      <div className="flex flex-wrap items-start gap-2">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={2}
          placeholder="Append an entry (e.g. 're-tested on Q1-2026 data, return +11.4%')"
          className="min-w-[240px] flex-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none"
        />
        <button
          type="button"
          onClick={submit}
          disabled={busy || !draft.trim()}
          className="rounded-md bg-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Saving…" : "Append"}
        </button>
      </div>
      {err && <div className="mt-2 text-[10px] text-bear">{err}</div>}
    </div>
  );
}

// ------------------------------------------------------ children card ----

function ChildrenCard({
  children,
  onSelect,
}: {
  children: ProfileMeta[];
  onSelect: (name: string) => void;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h3 className="mb-2 text-sm font-semibold text-slate-200">
        Versions based on this profile ({children.length})
      </h3>
      <ul className="space-y-1">
        {children.map((c) => (
          <li key={c.name}>
            <button
              type="button"
              onClick={() => onSelect(c.name)}
              className="flex w-full items-center justify-between gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-2 py-1 text-left hover:bg-slate-900"
            >
              <span className="font-mono text-xs text-slate-200">
                {c.name}
              </span>
              <span className="flex items-center gap-2">
                <PerformanceBadge perf={c.performance_preview} />
                <span className="text-[10px] text-slate-500">
                  {c.created_at ? formatDate(c.created_at) : ""}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// =====================================================================
// Helpers
// =====================================================================

function EmptyState({ onRefresh }: { onRefresh: () => void }) {
  return (
    <div className="space-y-4 rounded-lg border border-dashed border-slate-800 bg-slate-900/40 p-8 text-center">
      <div className="text-sm font-semibold text-slate-200">
        No profiles saved yet
      </div>
      <p className="text-[11px] text-slate-500">
        Run a backtest or sweep that looks promising, then click
        <em> "Save as profile"</em> on the run in History — or use the
        Save-as… button in the Backtest / Live form. Each saved profile
        captures the params <em>and</em> the baseline stats, so you can
        iterate over time and watch the performance improve.
      </p>
      <button
        type="button"
        onClick={onRefresh}
        className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
      >
        Refresh
      </button>
    </div>
  );
}

function useLineage(doc: ProfileDoc, profiles: ProfileMeta[]): ProfileMeta[] {
  return useMemo(() => {
    const byName = new Map(profiles.map((p) => [p.name, p]));
    const chain: ProfileMeta[] = [];
    let cursor = doc.parent;
    const seen = new Set<string>();
    while (cursor && !seen.has(cursor)) {
      seen.add(cursor);
      const meta = byName.get(cursor);
      if (!meta) break;
      chain.unshift(meta); // ancestors first → current last
      cursor = meta.parent;
    }
    return chain;
  }, [doc, profiles]);
}

/** Propose "name-v2" or bump the trailing version number. Never
 *  returns something identical to the input. */
function suggestNextName(current: string): string {
  // Trailing "-v<num>" wins so "btc-4h-adx-v2" -> "btc-4h-adx-v3".
  const m = current.match(/^(.*?-v)(\d+)$/i);
  if (m) return `${m[1]}${parseInt(m[2], 10) + 1}`;
  return `${current}-v2`;
}

function isValidName(s: string): boolean {
  return /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$/.test(s);
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
