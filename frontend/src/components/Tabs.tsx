import { clsx } from "clsx";

export interface Tab<T extends string> {
  id: T;
  label: string;
  badge?: string | number;
}

interface Props<T extends string> {
  tabs: Tab<T>[];
  value: T;
  onChange: (value: T) => void;
}

export function Tabs<T extends string>({ tabs, value, onChange }: Props<T>) {
  return (
    <div className="flex flex-wrap gap-1 border-b border-slate-800">
      {tabs.map((tab) => {
        const active = tab.id === value;
        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => onChange(tab.id)}
            className={clsx(
              "relative -mb-px px-4 py-2 text-sm font-medium transition-colors",
              active
                ? "border-b-2 border-slate-300 text-slate-100"
                : "border-b-2 border-transparent text-slate-500 hover:text-slate-300"
            )}
          >
            {tab.label}
            {tab.badge !== undefined && tab.badge !== "" && (
              <span
                className={clsx(
                  "ml-2 rounded-full px-1.5 py-0.5 text-[10px]",
                  active
                    ? "bg-slate-700 text-slate-200"
                    : "bg-slate-800 text-slate-400"
                )}
              >
                {tab.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
