import { clsx } from "clsx";

interface Props {
  label: string;
  value: string;
  sub?: string;
  tone?: "neutral" | "positive" | "negative";
}

export function MetricCard({ label, value, sub, tone = "neutral" }: Props) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div
        className={clsx("mt-2 font-mono text-2xl font-semibold", {
          "text-slate-100": tone === "neutral",
          "text-bull": tone === "positive",
          "text-bear": tone === "negative",
        })}
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}
