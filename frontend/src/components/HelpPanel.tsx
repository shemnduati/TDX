import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";

/** Tab ids the help panel can deep-link to. */
export type HelpNavTab =
  | "current"
  | "backtest"
  | "live"
  | "sweep"
  | "walkforward"
  | "regimes"
  | "portfolio"
  | "automation"
  | "history"
  | "compare"
  | "profiles";

interface Section {
  id: string;
  title: string;
  tab?: HelpNavTab;
}

const SECTIONS: Section[] = [
  { id: "overview", title: "Overview" },
  { id: "quick-start", title: "Quick start", tab: "backtest" },
  { id: "backtest", title: "Backtest", tab: "backtest" },
  { id: "profiles", title: "Profiles", tab: "profiles" },
  { id: "walkforward", title: "Walk-forward", tab: "walkforward" },
  { id: "sweep", title: "Parameter sweep", tab: "sweep" },
  { id: "regimes", title: "Regimes & sessions", tab: "regimes" },
  { id: "portfolio", title: "Portfolio", tab: "portfolio" },
  { id: "live", title: "Live paper trading", tab: "live" },
  { id: "automation", title: "Automation", tab: "automation" },
  { id: "history", title: "History & compare", tab: "history" },
  { id: "workflow", title: "Recommended workflow" },
  { id: "troubleshooting", title: "Troubleshooting" },
  { id: "glossary", title: "Glossary" },
];

interface Props {
  onNavigateTab: (tab: HelpNavTab) => void;
}

function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-800 text-xs font-semibold text-slate-300">
        {n}
      </span>
      <div>
        <p className="font-medium text-slate-200">{title}</p>
        <div className="mt-1 text-sm leading-relaxed text-slate-400">{children}</div>
      </div>
    </li>
  );
}

function Tip({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-2 rounded-md border border-slate-700/60 bg-slate-800/40 px-3 py-2 text-xs text-slate-400">
      <span className="font-semibold text-slate-300">Tip: </span>
      {children}
    </p>
  );
}

function GoToTab({
  label,
  tab,
  onNavigate,
}: {
  label: string;
  tab: HelpNavTab;
  onNavigate: (tab: HelpNavTab) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onNavigate(tab)}
      className="mt-2 inline-flex items-center gap-1 rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 hover:text-slate-100"
    >
      Open {label} tab →
    </button>
  );
}

function SectionBlock({
  id,
  title,
  tab,
  onNavigate,
  children,
}: {
  id: string;
  title: string;
  tab?: HelpNavTab;
  onNavigate: (tab: HelpNavTab) => void;
  children: React.ReactNode;
}) {
  return (
    <section id={`help-${id}`} className="scroll-mt-24">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2">
        <h2 className="text-base font-semibold text-slate-100">{title}</h2>
        {tab && <GoToTab label={title} tab={tab} onNavigate={onNavigate} />}
      </div>
      <div className="space-y-4 text-sm text-slate-400">{children}</div>
    </section>
  );
}

export function HelpPanel({ onNavigateTab }: Props) {
  const [active, setActive] = useState("overview");
  const mainRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = mainRef.current;
    if (!root) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible[0]?.target.id) {
          setActive(visible[0].target.id.replace("help-", ""));
        }
      },
      { root, rootMargin: "-10% 0px -70% 0px", threshold: [0, 0.25, 0.5] }
    );

    for (const s of SECTIONS) {
      const el = root.querySelector(`#help-${s.id}`);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  const scrollTo = (id: string) => {
    const el = mainRef.current?.querySelector(`#help-${id}`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
    setActive(id);
  };

  return (
    <div className="flex gap-6">
      {/* Sidebar TOC */}
      <nav className="hidden w-48 shrink-0 lg:block">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          On this page
        </p>
        <ul className="space-y-0.5">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => scrollTo(s.id)}
                className={clsx(
                  "w-full rounded-md px-2 py-1.5 text-left text-xs transition-colors",
                  active === s.id
                    ? "bg-slate-800 text-slate-100"
                    : "text-slate-500 hover:bg-slate-900 hover:text-slate-300"
                )}
              >
                {s.title}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {/* Main content */}
      <div
        ref={mainRef}
        className="max-h-[calc(100vh-12rem)] flex-1 space-y-10 overflow-y-auto pr-2"
      >
        {/* Hero */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
          <h1 className="text-lg font-semibold text-slate-100">
            How to use TDX
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-400">
            TDX is a paper-trading research dashboard. You configure a strategy,
            run historical backtests, validate with walk-forward analysis, and
            optionally run live shadow trading — all without risking real capital.
            This guide walks you through each tab in the order most new users
            should follow.
          </p>
        </div>

        <SectionBlock id="overview" title="Overview" onNavigate={onNavigateTab}>
          <p>
            The dashboard is organised around a simple loop:{" "}
            <strong className="text-slate-300">configure → backtest → validate → save → monitor</strong>.
            Each tab handles one step of that loop.
          </p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {[
              ["Backtest", "Run a strategy on historical OHLCV data"],
              ["Walk-forward", "Test whether params generalise out-of-sample"],
              ["Profiles", "Save and version named parameter presets"],
              ["Regimes", "See which market conditions each strategy likes"],
              ["Live", "Paper-trade against the live feed"],
              ["Automation", "Tournament, divergence, and go-live readiness"],
            ].map(([name, desc]) => (
              <div
                key={name}
                className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2"
              >
                <p className="text-xs font-medium text-slate-200">{name}</p>
                <p className="text-xs text-slate-500">{desc}</p>
              </div>
            ))}
          </div>
        </SectionBlock>

        <SectionBlock
          id="quick-start"
          title="Quick start (first 10 minutes)"
          tab="backtest"
          onNavigate={onNavigateTab}
        >
          <ol className="space-y-4">
            <Step n={1} title="Open the Backtest tab">
              Pick a symbol (e.g. BTC/USDT), timeframe (start with 1h or 4h),
              and strategy. Leave most filters off for your first run.
              <GoToTab label="Backtest" tab="backtest" onNavigate={onNavigateTab} />
            </Step>
            <Step n={2} title="Click Run backtest">
              Review the equity curve, metrics cards, and trade table on the
              Current tab after the run completes.
              <GoToTab label="Current" tab="current" onNavigate={onNavigateTab} />
            </Step>
            <Step n={3} title="Save as a profile">
              Use the profile bar at the top of Backtest to save your config
              under a descriptive name like{" "}
              <code className="text-slate-300">btc-4h-ema-baseline</code>.
              <GoToTab label="Profiles" tab="profiles" onNavigate={onNavigateTab} />
            </Step>
            <Step n={4} title="Run walk-forward validation">
              Switch to Walk-forward, keep the same params, and start a run.
              Look for a ROBUST verdict and stable test-window returns.
              <GoToTab label="Walk-forward" tab="walkforward" onNavigate={onNavigateTab} />
            </Step>
            <Step n={5} title="Check regime & session heatmaps">
              On the Regimes tab, compute the matrix to see where your strategy
              has positive expectancy. Use Session view to spot time-of-day edges.
              <GoToTab label="Regimes" tab="regimes" onNavigate={onNavigateTab} />
            </Step>
          </ol>
        </SectionBlock>

        <SectionBlock
          id="backtest"
          title="Backtest tab"
          tab="backtest"
          onNavigate={onNavigateTab}
        >
          <p>
            Configure every parameter that affects signal generation and trade
            execution, then replay history bar-by-bar.
          </p>
          <ul className="ml-4 list-disc space-y-1">
            <li>
              <strong className="text-slate-300">Market</strong> — symbol,
              timeframe, number of bars fetched from the exchange.
            </li>
            <li>
              <strong className="text-slate-300">Strategy params</strong> —
              EMA periods, RSI thresholds, Donchian lookback, etc. Fields change
              based on the selected strategy.
            </li>
            <li>
              <strong className="text-slate-300">Filters</strong> — opt-in
              gates (ADX, volume, ATR, HTF trend, MACD). Toggle each filter on
              before its sub-fields become active.
            </li>
            <li>
              <strong className="text-slate-300">Session filter</strong> —
              restrict entries to specific UTC sessions (asia, london, overlap,
              ny, off) or block weekends. Leave all unchecked to trade all hours.
            </li>
            <li>
              <strong className="text-slate-300">Risk</strong> — allocation,
              stop-loss / take-profit, ATR sizing, slippage, half-spread (backtest
              cost model), max spread (live-only entry gate from real bid/ask), and
              funding (for perpetual-style simulation).
            </li>
          </ul>
          <Tip>
            After running, results appear on the Current tab. Every run is also
            saved automatically to History so you can revisit or compare later.
          </Tip>
        </SectionBlock>

        <SectionBlock
          id="profiles"
          title="Profiles tab"
          tab="profiles"
          onNavigate={onNavigateTab}
        >
          <p>
            Profiles are named, version-controlled JSON presets stored in{" "}
            <code className="text-slate-300">profiles/</code>. They let you
            reuse a proven configuration without re-entering dozens of fields.
          </p>
          <ol className="ml-4 list-decimal space-y-2">
            <li>
              Save from Backtest or Live using the profile bar, or from History
              by cloning a run.
            </li>
            <li>
              Apply a profile to Backtest or Live — the form loads all saved
              params and shows an &quot;Active: name&quot; badge.
            </li>
            <li>
              Re-baseline via walk-forward: select profiles and run batch WFO to
              refresh params and performance baselines from recent data.
            </li>
          </ol>
          <Tip>
            Profile names like{" "}
            <code className="text-slate-300">btc-15m-donchian-breakout-HTF</code>{" "}
            make it easy to identify symbol, timeframe, and strategy at a glance.
          </Tip>
        </SectionBlock>

        <SectionBlock
          id="walkforward"
          title="Walk-forward tab"
          tab="walkforward"
          onNavigate={onNavigateTab}
        >
          <p>
            Walk-forward optimization (WFO) splits history into rolling train /
            test windows. Parameters are chosen on the train slice only; test
            performance is truly out-of-sample within each window.
          </p>
          <ul className="ml-4 list-disc space-y-1">
            <li>
              <strong className="text-slate-300">Train / test bars</strong> —
              window sizes. Larger train = more data to tune on; larger test =
              more reliable OOS read.
            </li>
            <li>
              <strong className="text-slate-300">Train engine</strong> — Grid
              searches a small candidate matrix; Optuna (Bayesian) requires{" "}
              <code className="text-slate-300">pip install optuna</code> and
              falls back to grid automatically if missing.
            </li>
            <li>
              <strong className="text-slate-300">Stability heatmap</strong> —
              shows how often each parameter value was selected across windows.
              Flat, consistent choices = robust; wild swings = overfit.
            </li>
            <li>
              <strong className="text-slate-300">Final OOS holdout</strong> —
              the last 25% of bars is never used during WFO tuning; it is
              evaluated once at the end as a final sanity check.
            </li>
          </ul>
          <Tip>
            A good backtest that fails walk-forward is a classic overfit signal.
            Always validate before promoting a profile to live paper trading.
          </Tip>
        </SectionBlock>

        <SectionBlock
          id="sweep"
          title="Parameter sweep tab"
          tab="sweep"
          onNavigate={onNavigateTab}
        >
          <p>
            Sweeps run a Cartesian grid of parameter combinations and save every
            result to History. Use this for broad exploration before narrowing
            down with walk-forward.
          </p>
          <ol className="ml-4 list-decimal space-y-2">
            <li>Select the fields you want to vary (strategy, timeframe, EMA periods, etc.).</li>
            <li>
              Enter comma-separated values for each field — e.g.{" "}
              <code className="text-slate-300">12, 20, 26</code> for EMA short.
            </li>
            <li>Start the sweep and monitor progress on the tab badge.</li>
            <li>
              When done, go to History, select interesting runs, and Compare
              them side-by-side.
            </li>
          </ol>
          <Tip>
            Keep sweep grids small (under ~200 combinations). Large sweeps
            take time and increase overfit risk without WFO validation.
          </Tip>
        </SectionBlock>

        <SectionBlock
          id="regimes"
          title="Regimes & sessions tab"
          tab="regimes"
          onNavigate={onNavigateTab}
        >
          <p>
            Analytics-only heatmaps that show per-strategy expectancy broken
            down by market condition. No trades are blocked here — this is for
            research.
          </p>
          <ul className="ml-4 list-disc space-y-1">
            <li>
              <strong className="text-slate-300">Regime view</strong> — 3-axis
              labels (trend × volatility × microstructure) computed on every bar.
            </li>
            <li>
              <strong className="text-slate-300">Session view</strong> — UTC
              buckets: asia (00–07), london (07–13), overlap (13–16), ny
              (16–22), off (22–24).
            </li>
            <li>
              <strong className="text-slate-300">Weekend split</strong> —
              separates weekday vs weekend performance within each session.
            </li>
            <li>
              Green cells = positive expectancy %; red = negative. Use the min-trades
              filter to ignore thin buckets.
            </li>
          </ul>
          <Tip>
            If you see a strong session asymmetry (&gt;50 bps delta with ≥30
            trades), enable the Session filter on Backtest to trade only those
            hours, then re-run walk-forward to confirm the edge holds OOS.
          </Tip>
        </SectionBlock>

        <SectionBlock
          id="portfolio"
          title="Portfolio tab"
          tab="portfolio"
          onNavigate={onNavigateTab}
        >
          <p>
            Run multiple strategies concurrently with portfolio-level risk
            controls instead of evaluating them one at a time.
          </p>
          <ul className="ml-4 list-disc space-y-1">
            <li>
              <strong className="text-slate-300">Weights</strong> — JSON map of
              strategy name → allocation weight (e.g.{" "}
              <code className="text-slate-300">
                {"{"}"ema_crossover": 0.5, "rsi_mean_reversion": 0.5{"}"}
              </code>
              ).
            </li>
            <li>
              <strong className="text-slate-300">Risk config</strong> — max open
              positions, vol-target sizing, equity-curve circuit breaker, and
              correlation group caps.
            </li>
          </ul>
          <Tip>
            Portfolio mode is the intended path to live shadow trading: run the
            same multi-strategy book in paper mode and monitor divergence on the
            Automation tab.
          </Tip>
        </SectionBlock>

        <SectionBlock
          id="live"
          title="Live paper trading tab"
          tab="live"
          onNavigate={onNavigateTab}
        >
          <p>
            Connects to the exchange feed and runs your strategy in real time
            using the paper execution model (no real orders).
          </p>
          <ol className="ml-4 list-decimal space-y-2">
            <li>Load or configure params (ideally from a validated profile).</li>
            <li>Click Start — the status dot in the header turns green.</li>
            <li>
              Switch to Current to watch equity, open position, and recent fills
              update every few seconds.
            </li>
            <li>Click Stop when done. The session is preserved in History.</li>
          </ol>
          <Tip>
            Do not go live with real capital until Automation reports READY
            (30+ days of paper ≈ backtest divergence within thresholds).
          </Tip>
        </SectionBlock>

        <SectionBlock
          id="automation"
          title="Automation tab"
          tab="automation"
          onNavigate={onNavigateTab}
        >
          <p>
            Tools for ongoing maintenance and go-live readiness checks.
          </p>
          <ul className="ml-4 list-disc space-y-1">
            <li>
              <strong className="text-slate-300">Tournament (dry-run)</strong> —
              re-runs walk-forward on all profiles and classifies them as
              promoted, candidate, or demoted based on OOS performance.
            </li>
            <li>
              <strong className="text-slate-300">Divergence check</strong> —
              compares live paper fills against a backtest replay on the same
              bars. Reports entry/exit slippage and PnL deltas.
            </li>
            <li>
              <strong className="text-slate-300">Readiness check</strong> —
              aggregates divergence reports over a rolling window and returns
              READY / NOT_READY / NO_DATA.
            </li>
          </ul>
          <Tip>
            Adjust the threshold inputs before running checks. Tighter
            thresholds = stricter go-live gate.
          </Tip>
        </SectionBlock>

        <SectionBlock
          id="history"
          title="History & compare tabs"
          tab="history"
          onNavigate={onNavigateTab}
        >
          <p>
            Every backtest, sweep result, walk-forward run, and live session is
            persisted and listed in History.
          </p>
          <ul className="ml-4 list-disc space-y-1">
            <li>
              <strong className="text-slate-300">Open</strong> — load a run onto
              the Current tab for inspection.
            </li>
            <li>
              <strong className="text-slate-300">Clone</strong> — copy params
              into Backtest for editing.
            </li>
            <li>
              <strong className="text-slate-300">Save as profile</strong> —
              promote a good run to a reusable preset.
            </li>
            <li>
              <strong className="text-slate-300">Compare</strong> — select 2+
              runs in History, click Compare, and overlay equity curves on the
              Compare tab.
            </li>
          </ul>
        </SectionBlock>

        <SectionBlock
          id="workflow"
          title="Recommended workflow"
          onNavigate={onNavigateTab}
        >
          <div className="space-y-3">
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-emerald-400/80">
                Phase 1 — Explore
              </p>
              <p className="mt-1 text-xs">
                Backtest → Sweep (small grid) → Compare winners → Save profile
              </p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-amber-400/80">
                Phase 2 — Validate
              </p>
              <p className="mt-1 text-xs">
                Walk-forward → Regime/session heatmaps → Tune session filters →
                Re-baseline profile
              </p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-sky-400/80">
                Phase 3 — Scale
              </p>
              <p className="mt-1 text-xs">
                Portfolio backtest → Live paper trading → Automation divergence →
                Readiness gate
              </p>
            </div>
          </div>
        </SectionBlock>

        <SectionBlock
          id="troubleshooting"
          title="Troubleshooting"
          onNavigate={onNavigateTab}
        >
          <dl className="space-y-3">
            <div>
              <dt className="font-medium text-slate-300">
                ECONNREFUSED 127.0.0.1:5001
              </dt>
              <dd className="mt-1">
                The Flask API is not running. Start both servers with{" "}
                <code className="text-slate-300">npm run dev:with-api</code>{" "}
                from the <code className="text-slate-300">frontend/</code>{" "}
                directory, or run <code className="text-slate-300">python dashboard.py</code>{" "}
                separately.
              </dd>
            </div>
            <div>
              <dt className="font-medium text-slate-300">
                Optuna ImportError during tournament / rebaseline
              </dt>
              <dd className="mt-1">
                Optuna is optional. Install with{" "}
                <code className="text-slate-300">pip install optuna&gt;=3</code>{" "}
                or switch the train engine to Grid — the system falls back
                automatically when Optuna is absent.
              </dd>
            </div>
            <div>
              <dt className="font-medium text-slate-300">
                Backtest shows zero trades
              </dt>
              <dd className="mt-1">
                Check that filters aren&apos;t too restrictive (ADX, volume,
                session filter, time-of-day window). Try disabling all filters
                and reducing warmup by using fewer indicator periods.
              </dd>
            </div>
            <div>
              <dt className="font-medium text-slate-300">
                Walk-forward verdict FRAGILE
              </dt>
              <dd className="mt-1">
                Test-window returns are inconsistent or negative. Simplify the
                strategy (fewer filters), widen train windows, or reduce the
                tuning matrix size. Check the stability heatmap for parameter
                churn.
              </dd>
            </div>
            <div>
              <dt className="font-medium text-slate-300">
                Live status stuck on &quot;stopped&quot;
              </dt>
              <dd className="mt-1">
                Ensure the API is reachable and you clicked Start on the Live
                tab. Check the browser console and terminal for exchange
                connection errors.
              </dd>
            </div>
          </dl>
        </SectionBlock>

        <SectionBlock id="glossary" title="Glossary" onNavigate={onNavigateTab}>
          <dl className="grid gap-3 sm:grid-cols-2">
            {[
              ["ATR sizing", "Position size scaled by Average True Range instead of fixed % allocation."],
              ["Expectancy", "Average profit per trade as a % of initial balance."],
              ["HTF confirm", "Higher-timeframe trend filter — only trade in the direction of the HTF EMA."],
              ["OOS", "Out-of-sample — data the optimizer never saw during parameter selection."],
              ["Paper trading", "Simulated execution with realistic slippage, spread, and funding."],
              ["Profile", "A named, saved JSON preset of all strategy parameters."],
              ["Regime", "Combined label: trend (up/down/flat) × vol (low/mid/high) × microstructure."],
              ["Session", "UTC time bucket: asia, london, overlap, ny, or off."],
              ["Shadow trading", "Running paper mode against the live feed to detect execution drift."],
              ["WFO", "Walk-forward optimization — rolling train/test validation."],
            ].map(([term, def]) => (
              <div key={term} className="rounded-lg border border-slate-800 px-3 py-2">
                <dt className="text-xs font-medium text-slate-200">{term}</dt>
                <dd className="mt-0.5 text-xs text-slate-500">{def}</dd>
              </div>
            ))}
          </dl>
        </SectionBlock>
      </div>
    </div>
  );
}
