import { clsx } from "clsx";
import type { LiveStatus } from "../types";
import { formatCurrency } from "../metrics";

interface Props {
  status: LiveStatus | null;
  canStart: boolean;
  busy?: boolean;
  onStart: () => void;
  onStop: () => void;
}

export function LiveControls({
  status,
  canStart,
  busy,
  onStart,
  onStop,
}: Props) {
  const running = status?.running ?? false;
  const lastTick = status?.last_tick_at
    ? new Date(status.last_tick_at * 1000)
    : null;
  const startedAt = status?.started_at
    ? new Date(status.started_at * 1000)
    : null;

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span
            className={clsx(
              "inline-block h-2.5 w-2.5 rounded-full",
              running ? "bg-bull animate-pulse" : "bg-slate-600"
            )}
          />
          <div>
            <div className="text-sm font-semibold">
              {running ? "Live bot running" : "Live bot stopped"}
            </div>
            <div className="text-xs text-slate-500">
              {running
                ? startedAt
                  ? `Started ${startedAt.toLocaleTimeString()}`
                  : "Running"
                : "Configure strategy and press Start."}
            </div>
          </div>
        </div>

        <div className="flex gap-2">
          {!running && (
            <button
              type="button"
              disabled={!canStart || busy}
              onClick={onStart}
              className={clsx(
                "rounded-md bg-bull/90 px-4 py-1.5 text-sm font-semibold text-slate-950 transition-colors",
                "hover:bg-bull disabled:cursor-not-allowed disabled:opacity-50"
              )}
            >
              {busy ? "Starting…" : "Start"}
            </button>
          )}
          {running && (
            <button
              type="button"
              disabled={busy}
              onClick={onStop}
              className={clsx(
                "rounded-md border border-bear/50 bg-bear/15 px-4 py-1.5 text-sm font-semibold text-bear transition-colors",
                "hover:bg-bear/25 disabled:cursor-not-allowed disabled:opacity-50"
              )}
            >
              {busy ? "Stopping…" : "Stop & save"}
            </button>
          )}
        </div>
      </div>

      {running && (
        <div className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
          <Stat
            label="Last signal"
            value={status?.last_signal ?? "—"}
            mono
          />
          <Stat
            label="Last price"
            value={
              status?.last_price ? formatCurrency(status.last_price) : "—"
            }
            mono
          />
          <Stat
            label="Balance"
            value={status?.balance ? formatCurrency(status.balance) : "—"}
            mono
          />
          <Stat
            label="Position"
            value={status?.position ?? "—"}
            mono
            tone={
              status?.position === "LONG"
                ? "bull"
                : status?.position === "SHORT"
                ? "bear"
                : undefined
            }
          />
          <Stat
            label="Last tick"
            value={
              lastTick
                ? `${Math.max(
                    0,
                    Math.floor((Date.now() - lastTick.getTime()) / 1000)
                  )}s ago`
                : "—"
            }
          />
          <Stat
            label="Strategy"
            value={status?.params?.strategy ?? "—"}
          />
          <Stat
            label="Symbol"
            value={`${status?.params?.symbol ?? "—"} ${
              status?.params?.timeframe ?? ""
            }`.trim()}
          />
        </div>
      )}

      {status?.last_error && (
        <div className="mt-4 rounded-md border border-bear/40 bg-bear/10 p-3 text-xs text-bear">
          <div className="font-semibold">Last error</div>
          <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px]">
            {status.last_error}
          </pre>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  mono,
  tone,
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: "bull" | "bear";
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div
        className={clsx(
          "mt-0.5 text-sm",
          mono && "font-mono",
          tone === "bull" && "text-bull",
          tone === "bear" && "text-bear",
          !tone && "text-slate-200"
        )}
      >
        {value}
      </div>
    </div>
  );
}
