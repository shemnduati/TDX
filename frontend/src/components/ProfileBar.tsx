import { clsx } from "clsx";
import { useState } from "react";
import type { ProfileMeta } from "../types";

/**
 * Profile selector / save-as bar rendered above StrategyForm.
 *
 * The parent owns the profile list + current-params state; this
 * component is purely presentational apart from a small local state
 * bag for the "save" modal. Keeping it dumb means both the Backtest
 * and Live views can reuse it without divergence.
 */

interface Props {
  profiles: ProfileMeta[];
  loading?: boolean;
  /** Currently-applied profile name, if any. Cleared by the parent
   *  when the user edits any field (so the label doesn't lie). */
  activeName?: string | null;
  onApply: (name: string) => void | Promise<void>;
  onSave?: (name: string, description: string) => void;
  onDelete?: (name: string) => void;
  onRefresh?: () => void;
  disabled?: boolean;
  /** Hide save/delete when the bar is only for loading presets (e.g. WF tab). */
  applyOnly?: boolean;
}

export function ProfileBar({
  profiles,
  loading,
  activeName,
  onApply,
  onSave,
  onDelete,
  onRefresh,
  disabled,
  applyOnly = false,
}: Props) {
  const [selected, setSelected] = useState<string>("");
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveDesc, setSaveDesc] = useState("");

  const choice = selected || activeName || "";
  const chosenMeta = profiles.find((p) => p.name === choice);

  const handleApply = () => {
    if (!choice) return;
    void onApply(choice);
  };

  const handleDelete = () => {
    if (!choice || !onDelete) return;
    if (!window.confirm(`Delete profile "${choice}"?`)) return;
    onDelete(choice);
    setSelected("");
  };

  const handleSave = () => {
    const name = saveName.trim();
    if (!name || !onSave) return;
    onSave(name, saveDesc.trim());
    setSaveOpen(false);
    setSaveName("");
    setSaveDesc("");
  };

  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Profile
          </div>
          <div className="text-[10px] text-slate-500">
            Per-market parameter presets. Applying a profile overwrites
            the form fields it specifies.
          </div>
        </div>
        {activeName && (
          <span className="rounded-full bg-slate-800/80 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-slate-300">
            Active: {activeName}
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={choice}
          disabled={disabled || loading}
          onChange={(e) => setSelected(e.target.value)}
          className="min-w-[220px] flex-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none"
        >
          <option value="">
            {loading
              ? "Loading profiles…"
              : profiles.length === 0
              ? "No profiles saved yet"
              : "— select a profile —"}
          </option>
          {profiles.map((p) => (
            <option key={p.name} value={p.name}>
              {formatProfileOption(p)}
            </option>
          ))}
        </select>

        <button
          type="button"
          disabled={disabled || !choice}
          onClick={handleApply}
          className="rounded-md bg-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          Apply
        </button>

        {!applyOnly && (
          <>
            <button
              type="button"
              disabled={disabled}
              onClick={() => setSaveOpen((v) => !v)}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {saveOpen ? "Cancel" : "Save as…"}
            </button>

            <button
              type="button"
              disabled={disabled || !choice}
              onClick={handleDelete}
              className="rounded-md border border-bear/40 px-3 py-1.5 text-xs text-bear hover:bg-bear/10 disabled:cursor-not-allowed disabled:opacity-30"
              title="Delete the selected profile"
            >
              Delete
            </button>
          </>
        )}

        {onRefresh && (
          <button
            type="button"
            disabled={disabled}
            onClick={onRefresh}
            className="rounded-md border border-slate-800 px-2 py-1 text-[10px] text-slate-500 hover:bg-slate-800 hover:text-slate-300"
            title="Reload profiles from disk"
          >
            ↻
          </button>
        )}
      </div>

      {chosenMeta && !saveOpen && (
        <div className="mt-2 text-[10px] text-slate-500">
          {chosenMeta.description || "(no description)"}
          {chosenMeta.override_count > 0 && (
            <span className="ml-2 text-slate-600">
              · {chosenMeta.override_count} overridden field
              {chosenMeta.override_count === 1 ? "" : "s"}
            </span>
          )}
        </div>
      )}

      {!applyOnly && saveOpen && (
        <div className="mt-3 space-y-2 rounded-md border border-slate-800 bg-slate-900/60 p-3">
          <div className="text-[10px] text-slate-500">
            Saves the CURRENT form values as a profile. Only fields that
            differ from config.py defaults are persisted, so the profile
            stays minimal.
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              placeholder="profile-name"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              className={clsx(
                "w-44 rounded-md border bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:outline-none",
                saveName && !isValidName(saveName)
                  ? "border-bear/60 focus:border-bear"
                  : "border-slate-700 focus:border-slate-500"
              )}
            />
            <input
              type="text"
              placeholder="description (optional)"
              value={saveDesc}
              onChange={(e) => setSaveDesc(e.target.value)}
              className="min-w-[220px] flex-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none"
            />
            <button
              type="button"
              disabled={disabled || !isValidName(saveName)}
              onClick={handleSave}
              className="rounded-md bg-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              Save
            </button>
          </div>
          {saveName && !isValidName(saveName) && (
            <div className="text-[10px] text-bear">
              Names must start with a letter/number and contain only
              letters, numbers, dots, dashes, or underscores.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatProfileOption(p: ProfileMeta): string {
  const { symbol, timeframe, strategy } = p.preview;
  const parts = [p.name];
  const marketBits = [symbol, timeframe].filter(Boolean).join(" ");
  if (marketBits || strategy) {
    const detail = [marketBits, strategy].filter(Boolean).join(" · ");
    parts.push(`(${detail})`);
  }
  return parts.join(" ");
}

// Mirror of the backend _NAME_RE regex in profiles.py. Kept as a
// plain literal string so the pattern is reviewable at a glance.
const NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$/;
function isValidName(s: string): boolean {
  return NAME_RE.test(s);
}
