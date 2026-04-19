import { clsx } from "clsx";
import type { DataSource } from "../types";

const OPTIONS: { id: DataSource; label: string }[] = [
  { id: "live", label: "Live" },
  { id: "backtest", label: "Backtest" },
];

interface Props {
  value: DataSource;
  onChange: (value: DataSource) => void;
}

export function SourceToggle({ value, onChange }: Props) {
  return (
    <div className="inline-flex rounded-lg border border-slate-800 bg-slate-900 p-0.5 text-xs">
      {OPTIONS.map((opt) => {
        const active = opt.id === value;
        return (
          <button
            key={opt.id}
            type="button"
            onClick={() => onChange(opt.id)}
            className={clsx(
              "rounded-md px-3 py-1 font-medium transition-colors",
              active
                ? "bg-slate-700 text-slate-100"
                : "text-slate-400 hover:text-slate-200"
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
