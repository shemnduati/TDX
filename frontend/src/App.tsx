import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AuthRequiredError,
  authLogout,
  authMe,
  deleteProfile,
  deleteRun,
  downloadWalkforwardReportJson,
  downloadWalkforwardStabilityCsv,
  downloadWalkforwardWindowsCsv,
  fetchAuthConfig,
  fetchDashboardData,
  fetchDefaults,
  fetchStrategies,
  fetchSymbols,
  getProfile,
  listProfiles,
  liveStart,
  liveStatus,
  liveStop,
  listRuns,
  loadRun,
  monitorDivergence,
  monitorReadiness,
  portfolioRun,
  renameRun,
  regimeExpectancy,
  sessionExpectancy,
  rebaselineProfilesWalkforward,
  runBacktest,
  saveProfile,
  sweepCancel,
  sweepStart,
  sweepStatus,
  tournamentRun,
  updateProfile,
  walkforwardCancel,
  walkforwardStart,
  walkforwardStability,
  walkforwardStatus,
} from "./api";
import type {
  BacktestRunResponse,
  DashboardData,
  DivergenceResponse,
  LiveStatus,
  PortfolioRunResponse,
  PortfolioRiskConfig,
  ReadinessResponse,
  RegimeExpectancyResponse,
  SessionExpectancyResponse,
  ProfileDoc,
  ProfileMeta,
  ProfilePerformance,
  ProfilesWalkforwardRebaselineStart,
  ProfilesWalkforwardRebaselineResponse,
  RunMeta,
  RunPayload,
  StrategyInfo,
  StrategyParams,
  SweepStatus,
  TournamentRunResponse,
  WalkforwardStart,
  WalkforwardStabilityResponse,
  WalkforwardStatus,
} from "./types";
import { MetricsCards } from "./components/MetricsCards";
import { EquityCurveChart } from "./components/EquityCurveChart";
import { EquityOverlayChart } from "./components/EquityOverlayChart";
import { PositionCard } from "./components/PositionCard";
import { TradeTable } from "./components/TradeTable";
import { StrategyForm } from "./components/StrategyForm";
import { OptInFiltersContext } from "./components/OptInFiltersContext";
import { RunList } from "./components/RunList";
import { LiveControls } from "./components/LiveControls";
import { ProfileBar } from "./components/ProfileBar";
import { ProfilesView } from "./components/ProfilesView";
import { Tabs, type Tab } from "./components/Tabs";
import { SweepPanel } from "./components/SweepPanel";
import { WalkforwardPanel } from "./components/WalkforwardPanel";
import { RegimePanel } from "./components/RegimePanel";
import { PortfolioPanel } from "./components/PortfolioPanel";
import { AutomationPanel } from "./components/AutomationPanel";
import { HelpPanel } from "./components/HelpPanel";
import { LoginPage } from "./components/LoginPage";
import { formatCurrency } from "./metrics";

const POLL_MS = 3000;

type TabId =
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
  | "profiles"
  | "help";

type CurrentSource =
  | { type: "live" }
  | { type: "backtest" }
  | { type: "run"; id: string; label: string; params: StrategyParams };

export default function App() {
  const [authReady, setAuthReady] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [loginUsername, setLoginUsername] = useState("admin");

  const [tab, setTab] = useState<TabId>("current");
  const [currentSource, setCurrentSource] = useState<CurrentSource>({
    type: "live",
  });
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [defaults, setDefaults] = useState<StrategyParams | null>(null);
  const [backtestParams, setBacktestParams] = useState<StrategyParams | null>(
    null
  );
  const [liveParams, setLiveParams] = useState<StrategyParams | null>(null);

  const [runs, setRuns] = useState<RunMeta[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [selectedRunIds, setSelectedRunIds] = useState<Set<string>>(new Set());
  const [runsDeleteBusy, setRunsDeleteBusy] = useState(false);

  // Profiles — see ProfileBar.tsx. activeProfile{Backtest,Live} track the
  // name of the last profile applied to each form, which the UI uses to
  // render an "Active: <name>" badge. We clear it whenever the user edits
  // any field so the badge never lies about what's in the form.
  const [profiles, setProfiles] = useState<ProfileMeta[]>([]);
  const [profilesLoading, setProfilesLoading] = useState(false);
  const [activeProfileBacktest, setActiveProfileBacktest] = useState<
    string | null
  >(null);
  const [activeProfileLive, setActiveProfileLive] = useState<string | null>(
    null
  );
  const [comparePayloads, setComparePayloads] = useState<RunPayload[]>([]);
  const [compareLoading, setCompareLoading] = useState(false);

  const [sweepState, setSweepState] = useState<SweepStatus | null>(null);
  const [sweepBusy, setSweepBusy] = useState(false);

  const [wfState, setWfState] = useState<WalkforwardStatus | null>(null);
  const [wfStability, setWfStability] =
    useState<WalkforwardStabilityResponse | null>(null);
  const [wfBusy, setWfBusy] = useState(false);
  const [regimeBusy, setRegimeBusy] = useState(false);
  const [regimeData, setRegimeData] = useState<RegimeExpectancyResponse | null>(null);
  const [sessionData, setSessionData] = useState<SessionExpectancyResponse | null>(null);
  const [portfolioBusy, setPortfolioBusy] = useState(false);
  const [portfolioResult, setPortfolioResult] = useState<PortfolioRunResponse | null>(null);
  const [automationBusy, setAutomationBusy] = useState(false);
  const [tournamentResult, setTournamentResult] =
    useState<TournamentRunResponse | null>(null);
  const [divergenceResult, setDivergenceResult] =
    useState<DivergenceResponse | null>(null);
  const [readinessResult, setReadinessResult] =
    useState<ReadinessResponse | null>(null);

  const [liveState, setLiveState] = useState<LiveStatus | null>(null);
  const [backtestBusy, setBacktestBusy] = useState(false);
  const [liveBusy, setLiveBusy] = useState(false);
  const [lastBacktest, setLastBacktest] =
    useState<BacktestRunResponse | null>(null);

  const lastUpdatedRef = useRef<Date | null>(null);
  const [, forceTick] = useState(0);

  // ------------------------------------------------ auth gate
  const refreshAuth = useCallback(async () => {
    const [cfg, me] = await Promise.all([fetchAuthConfig(), authMe()]);
    setAuthRequired(cfg.auth_required);
    setLoginUsername(cfg.username ?? "admin");
    setAuthenticated(me.authenticated);
    setAuthReady(true);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    refreshAuth().catch((e) => {
      setError(e instanceof Error ? e.message : String(e));
      setAuthReady(true);
    });
    return () => controller.abort();
  }, [refreshAuth]);

  const handleLogout = useCallback(async () => {
    try {
      await authLogout();
    } catch {
      /* session may already be gone */
    }
    setAuthenticated(false);
    setData(null);
  }, []);

  // ------------------------------------------------ boot: metadata + runs
  useEffect(() => {
    if (!authReady) return;
    if (authRequired && !authenticated) return;

    const controller = new AbortController();
    Promise.all([
      fetchStrategies(controller.signal),
      fetchDefaults(controller.signal),
      fetchSymbols(controller.signal).catch(() => ({ symbols: [] as string[] })),
    ])
      .then(([s, d, sym]) => {
        setStrategies(s.strategies);
        setDefaults(d);
        setBacktestParams(d);
        setLiveParams(d);
        setSymbols(sym.symbols);
      })
      .catch((e) => {
        if (e instanceof AuthRequiredError) {
          setAuthenticated(false);
          return;
        }
        setError(e instanceof Error ? e.message : String(e));
      });
    return () => controller.abort();
  }, [authReady, authRequired, authenticated]);

  const refreshRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const res = await listRuns();
      setRuns(res.runs);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunsLoading(false);
    }
  }, []);

  const refreshProfiles = useCallback(async () => {
    setProfilesLoading(true);
    try {
      const res = await listProfiles();
      setProfiles(res.profiles);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setProfilesLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshRuns();
    refreshProfiles();
  }, [refreshRuns, refreshProfiles]);

  // ------------------------------------- poll dashboard data for Current tab
  useEffect(() => {
    if (currentSource.type === "run") return; // static, loaded on demand

    let cancelled = false;
    const controller = new AbortController();
    setData(null);

    const load = async () => {
      try {
        const next = await fetchDashboardData(
          currentSource.type,
          controller.signal
        );
        if (cancelled) return;
        setData(next);
        lastUpdatedRef.current = new Date();
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      }
    };

    load();
    const id = window.setInterval(load, POLL_MS);
    const tick = window.setInterval(() => forceTick((n) => n + 1), 1000);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
      window.clearInterval(tick);
    };
  }, [currentSource]);

  // ----------------------------------------------------- poll live status
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await liveStatus();
        if (!cancelled) setLiveState(s);
      } catch {
        /* non-fatal; leave previous state */
      }
    };
    load();
    const id = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // ---------------------------------------------------- poll sweep status
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await sweepStatus();
        if (!cancelled) setSweepState(s);
      } catch {
        /* non-fatal */
      }
    };
    load();
    // Poll fast while a sweep is running, slowly otherwise.
    const interval = sweepState?.running ? 1500 : 5000;
    const id = window.setInterval(load, interval);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [sweepState?.running]);

  // ----------------------------------------------- poll walk-forward status
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [s, st] = await Promise.all([
          walkforwardStatus(),
          walkforwardStability(),
        ]);
        if (!cancelled) {
          setWfState(s);
          setWfStability(st);
        }
      } catch {
        /* non-fatal */
      }
    };
    load();
    const interval = wfState?.running ? 1500 : 5000;
    const id = window.setInterval(load, interval);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [wfState?.running]);

  // Refresh the runs list when a sweep produces new results.
  const sweepResultsCount = sweepState?.results.length ?? 0;
  useEffect(() => {
    if (sweepResultsCount > 0) refreshRuns();
  }, [sweepResultsCount, refreshRuns]);

  // --------------------------------------------------------------- actions
  const handleRunBacktest = useCallback(async () => {
    if (!backtestParams) return;
    setBacktestBusy(true);
    setError(null);
    try {
      const res = await runBacktest(backtestParams, { save: true });
      setLastBacktest(res);
      setData(res.data);
      setCurrentSource({ type: "backtest" });
      setTab("current");
      refreshRuns();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBacktestBusy(false);
    }
  }, [backtestParams, refreshRuns]);

  const handleLiveStart = useCallback(async () => {
    if (!liveParams) return;
    setLiveBusy(true);
    setError(null);
    try {
      const s = await liveStart(liveParams);
      setLiveState(s);
      setCurrentSource({ type: "live" });
      setTab("current");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLiveBusy(false);
    }
  }, [liveParams]);

  const handleLiveStop = useCallback(async () => {
    setLiveBusy(true);
    try {
      const s = await liveStop({ save: true });
      setLiveState(s);
      refreshRuns();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLiveBusy(false);
    }
  }, [refreshRuns]);

  const handleOpenRun = useCallback(async (id: string) => {
    setError(null);
    try {
      const res = await loadRun(id);
      setData(res.data);
      const merged = (defaults
        ? { ...defaults, ...res.meta.params }
        : res.meta.params) as StrategyParams;
      setCurrentSource({
        type: "run",
        id,
        label: res.meta.label,
        params: merged,
      });
      setTab("current");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [defaults]);

  const handleDeleteRun = useCallback(
    async (id: string) => {
      try {
        await deleteRun(id);
        if (currentSource.type === "run" && currentSource.id === id) {
          setCurrentSource({ type: "backtest" });
        }
        refreshRuns();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [currentSource, refreshRuns]
  );

  const handleDeleteSelectedRuns = useCallback(async () => {
    const ids = [...selectedRunIds];
    if (ids.length === 0) return;
    if (
      !window.confirm(
        `Delete ${ids.length} selected run(s)? This cannot be undone.`
      )
    ) {
      return;
    }
    setError(null);
    const idSet = new Set(ids);
    setRunsDeleteBusy(true);
    try {
      await Promise.all(ids.map((id) => deleteRun(id)));
      setCurrentSource((prev) =>
        prev.type === "run" && idSet.has(prev.id)
          ? { type: "backtest" }
          : prev
      );
      setSelectedRunIds(new Set());
      refreshRuns();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      refreshRuns();
    } finally {
      setRunsDeleteBusy(false);
    }
  }, [selectedRunIds, refreshRuns]);

  const handleRenameRun = useCallback(
    async (id: string, label: string) => {
      try {
        await renameRun(id, label);
        refreshRuns();
        setCurrentSource((prev) =>
          prev.type === "run" && prev.id === id ? { ...prev, label } : prev
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [refreshRuns]
  );

  const handleCloneRun = useCallback(
    (run: RunMeta) => {
      if (!defaults) return;
      // Merge the run's params on top of current defaults so any new Params
      // fields added since the run was saved (e.g. ATR knobs) don't arrive
      // as `undefined` and break the form.
      setBacktestParams({ ...defaults, ...run.params });
      // Cloning a run into the form does NOT correspond to any saved
      // profile — clear the badge so we don't mislead the user.
      setActiveProfileBacktest(null);
      setTab("backtest");
    },
    [defaults]
  );

  // --------------------------------------------------------- profiles ------
  // Applying a profile merges its sparse override set over the current
  // defaults, which gives the form a complete Params object even as new
  // fields are added to config.py. The target ("backtest" | "live")
  // decides which form's state to update and which active-profile badge
  // to set.
  const applyProfileTo = useCallback(
    async (
      target: "backtest" | "live",
      name: string
    ): Promise<StrategyParams | null> => {
      if (!defaults) return null;
      setError(null);
      try {
        const doc = await getProfile(name);
        const merged: StrategyParams = { ...defaults, ...doc.params };
        if (target === "backtest") {
          setBacktestParams(merged);
          setActiveProfileBacktest(name);
        } else {
          setLiveParams(merged);
          setActiveProfileLive(name);
        }
        return merged;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return null;
      }
    },
    [defaults]
  );

  // Saving uses the CURRENT form state as the source of truth. The
  // backend auto-minimises (drops fields matching config.py defaults),
  // so we don't need to compute a diff here. Performance is
  // auto-attached from whichever recent run these params came from:
  // - When saving from a run row, use that run's summary directly.
  // - When saving from the Backtest form, reuse the lastBacktest if
  //   its saved-run id matches the current params (approximation —
  //   we just require the strategy + market to match).
  const saveProfileFrom = useCallback(
    async (
      source:
        | {
            kind: "params";
            params: StrategyParams;
            target?: "backtest" | "live";
            parent?: string | null;
            changelogMessage?: string;
            performance?: ProfilePerformance | null;
          }
        | { kind: "run"; run: RunMeta },
      name: string,
      description: string
    ) => {
      setError(null);
      try {
        let params: StrategyParams;
        let src: string;
        let performance: ProfilePerformance | null | undefined;
        let parent: string | null | undefined;
        let changelogMessage: string | undefined;

        if (source.kind === "run") {
          params = source.run.params as StrategyParams;
          src = `run:${source.run.id} (${source.run.label})`;
          // Runs already carry a summary — attach it as the baseline.
          performance = {
            kind: source.run.kind,
            run_id: source.run.id,
            summary: source.run.summary as unknown as Record<string, unknown>,
          };
        } else {
          params = source.params;
          src = "dashboard form";
          parent = source.parent ?? null;
          changelogMessage = source.changelogMessage;
          performance = source.performance ?? null;
          // Convenience: if the user just ran a backtest in the same
          // session and the saved-run's params match the current form
          // state, reuse its summary as the baseline. "Matches" here
          // is a strict comparison on all StrategyParams fields; any
          // hand-edit after the backtest invalidates the reuse.
          if (!performance && lastBacktest?.summary && lastBacktest.saved) {
            const equal = paramsEqual(
              lastBacktest.saved.params as StrategyParams,
              params
            );
            if (equal) {
              performance = {
                kind: "backtest",
                run_id: lastBacktest.saved.id,
                summary: lastBacktest.summary as unknown as Record<
                  string,
                  unknown
                >,
              };
            }
          }
        }

        await saveProfile({
          name,
          params,
          description,
          source: src,
          parent,
          changelog_message: changelogMessage,
          performance: performance ?? undefined,
        });
        await refreshProfiles();
        if (source.kind === "params") {
          if (source.target === "live") setActiveProfileLive(name);
          else setActiveProfileBacktest(name);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [refreshProfiles, lastBacktest]
  );

  const handleLoadProfileFull = useCallback(async (name: string) => {
    return await getProfile(name);
  }, []);

  const handleLoadProfileIntoBacktest = useCallback(
    (doc: ProfileDoc) => {
      if (!defaults) return;
      const merged: StrategyParams = { ...defaults, ...doc.params };
      setBacktestParams(merged);
      setActiveProfileBacktest(doc.name);
      setTab("backtest");
    },
    [defaults]
  );

  const handleCreateProfileVersion = useCallback(
    async (input: {
      name: string;
      description: string;
      changelogMessage: string;
      parent: string;
      fromDoc: ProfileDoc;
    }) => {
      if (!defaults) return;
      setError(null);
      // Child inherits all params from the source profile — callers
      // can later Load-into-Backtest, tweak, and save a further
      // version to record a genuine delta.
      const merged: StrategyParams = { ...defaults, ...input.fromDoc.params };
      await saveProfileFrom(
        {
          kind: "params",
          params: merged,
          target: "backtest",
          parent: input.parent,
          changelogMessage: input.changelogMessage,
          performance: input.fromDoc.performance ?? null,
        },
        input.name,
        input.description
      );
    },
    [defaults, saveProfileFrom]
  );

  const handleEditProfileDescription = useCallback(
    async (name: string, description: string) => {
      await updateProfile(name, { description });
      await refreshProfiles();
    },
    [refreshProfiles]
  );

  const handleAppendProfileChangelog = useCallback(
    async (name: string, message: string) => {
      await updateProfile(name, { append_message: message });
      await refreshProfiles();
    },
    [refreshProfiles]
  );

  const handleDeleteProfile = useCallback(
    async (name: string) => {
      setError(null);
      try {
        await deleteProfile(name);
        if (activeProfileBacktest === name) setActiveProfileBacktest(null);
        if (activeProfileLive === name) setActiveProfileLive(null);
        await refreshProfiles();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [activeProfileBacktest, activeProfileLive, refreshProfiles]
  );

  const handleRebaselineProfilesWalkforward = useCallback(
    async (
      body: ProfilesWalkforwardRebaselineStart = {}
    ): Promise<ProfilesWalkforwardRebaselineResponse> => {
      setError(null);
      const res = await rebaselineProfilesWalkforward(body);
      if (!body.dry_run) {
        await refreshProfiles();
      }
      return res;
    },
    [refreshProfiles]
  );

  // Wrapped setters so any hand-edit to the form automatically drops
  // the active-profile badge — otherwise the UI would keep claiming
  // "Active: btc-4h-adx" while the user was merrily tweaking values.
  const handleBacktestParamsChange = useCallback((p: StrategyParams) => {
    setBacktestParams(p);
    setActiveProfileBacktest(null);
  }, []);
  const handleLiveParamsChange = useCallback((p: StrategyParams) => {
    setLiveParams(p);
    setActiveProfileLive(null);
  }, []);

  const handleToggleSelected = useCallback((id: string) => {
    setSelectedRunIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleClearSelection = useCallback(() => {
    setSelectedRunIds(new Set());
  }, []);

  const handleOpenCompare = useCallback(async () => {
    if (selectedRunIds.size === 0) return;
    setCompareLoading(true);
    setError(null);
    try {
      const ids = Array.from(selectedRunIds);
      const payloads = await Promise.all(ids.map((id) => loadRun(id)));
      setComparePayloads(payloads);
      setTab("compare");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCompareLoading(false);
    }
  }, [selectedRunIds]);

  const handleSweepStart = useCallback(
    async (body: {
      base_params: Partial<StrategyParams>;
      matrix: Record<string, (string | number | boolean)[]>;
      label_prefix: string;
    }) => {
      setSweepBusy(true);
      setError(null);
      try {
        const s = await sweepStart(body);
        setSweepState(s);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setSweepBusy(false);
      }
    },
    []
  );

  const handleSweepCancel = useCallback(async () => {
    setSweepBusy(true);
    try {
      const s = await sweepCancel();
      setSweepState(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSweepBusy(false);
    }
  }, []);

  const handleWfStart = useCallback(
    async (body: WalkforwardStart) => {
      setWfBusy(true);
      setError(null);
      try {
        const s = await walkforwardStart(body);
        setWfState(s);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setWfBusy(false);
      }
    },
    []
  );

  const handleWfCancel = useCallback(async () => {
    setWfBusy(true);
    try {
      const s = await walkforwardCancel();
      setWfState(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setWfBusy(false);
    }
  }, []);

  const handleWfDownloadStabilityCsv = useCallback(async () => {
    setError(null);
    try {
      await downloadWalkforwardStabilityCsv();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const handleWfDownloadWindowsCsv = useCallback(async () => {
    setError(null);
    try {
      await downloadWalkforwardWindowsCsv();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const handleWfDownloadReportJson = useCallback(async () => {
    setError(null);
    try {
      await downloadWalkforwardReportJson();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const handleRegimeRun = useCallback(async () => {
    if (!backtestParams) return;
    setRegimeBusy(true);
    setError(null);
    try {
      const res = await regimeExpectancy({ params: backtestParams });
      setRegimeData(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRegimeBusy(false);
    }
  }, [backtestParams]);

  const handleSessionRun = useCallback(
    async (weekendSplit: boolean) => {
      if (!backtestParams) return;
      setRegimeBusy(true);
      setError(null);
      try {
        const res = await sessionExpectancy({
          params: backtestParams,
          weekend_split: weekendSplit,
        });
        setSessionData(res);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setRegimeBusy(false);
      }
    },
    [backtestParams]
  );

  const handlePortfolioRun = useCallback(
    async (weights: Record<string, number>, risk: PortfolioRiskConfig) => {
      if (!backtestParams) return;
      setPortfolioBusy(true);
      setError(null);
      try {
        const res = await portfolioRun({
          params: backtestParams,
          weights,
          risk,
        });
        setPortfolioResult(res);
        if (res.saved?.id) {
          await refreshRuns();
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setPortfolioBusy(false);
      }
    },
    [backtestParams, refreshRuns]
  );

  const handleTournamentRun = useCallback(async () => {
    setAutomationBusy(true);
    setError(null);
    try {
      const res = await tournamentRun({ dry_run: true });
      setTournamentResult(res);
      await refreshProfiles();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAutomationBusy(false);
    }
  }, [refreshProfiles]);

  const handleDivergenceCheck = useCallback(
    async (thresholds: Record<string, number>) => {
    setAutomationBusy(true);
    setError(null);
    try {
        const res = await monitorDivergence({ thresholds });
        setDivergenceResult(res);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setAutomationBusy(false);
      }
    },
    []
  );

  const handleReadinessCheck = useCallback(
    async (raw: Record<string, number>) => {
      setAutomationBusy(true);
      setError(null);
      try {
        const {
          min_avg_timestamp_match_rate,
          max_avg_mean_abs_pnl_delta_pct,
          ...thresholds
        } = raw;
        const res = await monitorReadiness({
          days: 30,
          thresholds,
          min_avg_timestamp_match_rate,
          max_avg_mean_abs_pnl_delta_pct,
        });
        setReadinessResult(res);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setAutomationBusy(false);
      }
    },
    []
  );

  // Drop deleted runs from the selection so the Compare button count stays sane.
  useEffect(() => {
    const existing = new Set(runs.map((r) => r.id));
    setSelectedRunIds((prev) => {
      const next = new Set<string>();
      prev.forEach((id) => {
        if (existing.has(id)) next.add(id);
      });
      return next.size === prev.size ? prev : next;
    });
  }, [runs]);

  // When defaults arrive after a saved run was opened, merge so missing keys
  // (new Params fields) don't read as undefined in the filters panel.
  useEffect(() => {
    if (!defaults) return;
    setCurrentSource((prev) => {
      if (prev.type !== "run") return prev;
      return { ...prev, params: { ...defaults, ...prev.params } };
    });
  }, [defaults]);

  const currentParamsSnapshot = useMemo((): StrategyParams | null => {
    if (currentSource.type === "run") return currentSource.params;
    if (currentSource.type === "live") {
      const p = liveState?.params ?? liveParams;
      return p ?? null;
    }
    const saved = lastBacktest?.saved?.params;
    return (saved as StrategyParams | undefined) ?? null;
  }, [
    currentSource,
    liveState?.params,
    liveParams,
    lastBacktest?.saved?.params,
  ]);

  const statusDot = useMemo(() => {
    if (currentSource.type === "run") return "bg-slate-500";
    if (currentSource.type === "backtest") return "bg-amber-400";
    if (liveState?.running) return "bg-bull animate-pulse";
    return "bg-slate-600";
  }, [currentSource, liveState]);

  const statusLabel = useMemo(() => {
    if (currentSource.type === "run") return `Run · ${currentSource.label}`;
    if (currentSource.type === "backtest") {
      return data ? "Backtest loaded" : "Loading backtest…";
    }
    if (liveState?.running) {
      const last = lastUpdatedRef.current;
      if (!last) return "Live · connecting…";
      const secs = Math.max(
        0,
        Math.floor((Date.now() - last.getTime()) / 1000)
      );
      return `Live · updated ${secs}s ago`;
    }
    return "Live bot stopped";
  }, [currentSource, data, liveState]);

  if (!authReady) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-sm text-slate-500">
        Loading…
      </div>
    );
  }

  if (authRequired && !authenticated) {
    return (
      <LoginPage
        defaultUsername={loginUsername}
        onSuccess={() => {
          void refreshAuth();
        }}
      />
    );
  }

  const tabDefs: Tab<TabId>[] = [
    { id: "current", label: "Current" },
    { id: "backtest", label: "Backtest" },
    { id: "live", label: "Live" },
    {
      id: "sweep",
      label: "Sweep",
      badge: sweepState?.running
        ? `${sweepState.completed}/${sweepState.total}`
        : undefined,
    },
    {
      id: "walkforward",
      label: "Walk-forward",
      badge: wfState?.running
        ? `${wfState.completed}/${wfState.total || "?"}`
        : wfState?.summary?.verdict === "ROBUST"
        ? "ROBUST"
        : undefined,
    },
    {
      id: "regimes",
      label: "Regimes",
      badge: regimeData?.rows?.length || undefined,
    },
    {
      id: "portfolio",
      label: "Portfolio",
      badge: portfolioResult?.result?.combined?.total_trades || undefined,
    },
    {
      id: "automation",
      label: "Automation",
      badge: readinessResult?.summary?.verdict === "READY" ? "READY" : undefined,
    },
    { id: "history", label: "History", badge: runs.length || undefined },
    {
      id: "compare",
      label: "Compare",
      badge: comparePayloads.length || undefined,
    },
    {
      id: "profiles",
      label: "Profiles",
      badge: profiles.length || undefined,
    },
    { id: "help", label: "How to" },
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              TDX · Trading Dashboard
            </h1>
            <p className="text-xs text-slate-500">
              Backtest, live-test & save strategies · paper trading
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <span className={`inline-block h-2 w-2 rounded-full ${statusDot}`} />
            <span className="text-slate-400">{statusLabel}</span>
            {authRequired && (
              <button
                type="button"
                onClick={() => void handleLogout()}
                className="rounded-md border border-slate-700 px-2 py-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              >
                Sign out
              </button>
            )}
          </div>
        </div>
        <div className="mx-auto max-w-7xl px-6">
          <Tabs tabs={tabDefs} value={tab} onChange={setTab} />
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-6 px-6 py-6">
        {error && (
          <div className="flex items-start justify-between gap-3 rounded-lg border border-bear/40 bg-bear/10 px-4 py-3 text-sm text-bear">
            <div className="whitespace-pre-wrap">{error}</div>
            <button
              className="text-xs text-bear/80 hover:text-bear"
              onClick={() => setError(null)}
              type="button"
            >
              dismiss
            </button>
          </div>
        )}

        {tab === "current" && (
          <CurrentView
            data={data}
            currentSource={currentSource}
            filterParams={currentParamsSnapshot}
            onSwitchSource={(s) => setCurrentSource(s)}
          />
        )}

        {tab === "backtest" && (
          <BacktestView
            params={backtestParams}
            strategies={strategies}
            symbols={symbols}
            defaults={defaults}
            onChange={handleBacktestParamsChange}
            onRun={handleRunBacktest}
            busy={backtestBusy}
            last={lastBacktest}
            profiles={profiles}
            profilesLoading={profilesLoading}
            activeProfile={activeProfileBacktest}
            onApplyProfile={(name) => applyProfileTo("backtest", name)}
            onSaveProfile={(name, desc) => {
              if (!backtestParams) return;
              saveProfileFrom(
                { kind: "params", params: backtestParams, target: "backtest" },
                name,
                desc
              );
            }}
            onDeleteProfile={handleDeleteProfile}
            onRefreshProfiles={refreshProfiles}
          />
        )}

        {tab === "live" && (
          <LiveView
            params={liveParams}
            strategies={strategies}
            symbols={symbols}
            defaults={defaults}
            onChange={handleLiveParamsChange}
            status={liveState}
            busy={liveBusy}
            onStart={handleLiveStart}
            onStop={handleLiveStop}
            profiles={profiles}
            profilesLoading={profilesLoading}
            activeProfile={activeProfileLive}
            onApplyProfile={(name) => applyProfileTo("live", name)}
            onSaveProfile={(name, desc) => {
              if (!liveParams) return;
              saveProfileFrom(
                { kind: "params", params: liveParams, target: "live" },
                name,
                desc
              );
            }}
            onDeleteProfile={handleDeleteProfile}
            onRefreshProfiles={refreshProfiles}
          />
        )}

        {tab === "sweep" && (
          <SweepPanel
            defaults={defaults}
            status={sweepState}
            busy={sweepBusy}
            error={sweepState?.error ?? null}
            onStart={handleSweepStart}
            onCancel={handleSweepCancel}
            onJumpToHistory={() => setTab("history")}
          />
        )}

        {tab === "walkforward" && (
          <WalkforwardPanel
            defaults={defaults}
            params={backtestParams}
            onParamsChange={handleBacktestParamsChange}
            status={wfState}
            stability={wfStability}
            busy={wfBusy}
            error={wfState?.error ?? null}
            profiles={profiles}
            profilesLoading={profilesLoading}
            activeProfile={activeProfileBacktest}
            onApplyProfile={(name) => applyProfileTo("backtest", name)}
            onRefreshProfiles={refreshProfiles}
            onStart={handleWfStart}
            onCancel={handleWfCancel}
            onDownloadStabilityCsv={handleWfDownloadStabilityCsv}
            onDownloadWindowsCsv={handleWfDownloadWindowsCsv}
            onDownloadReportJson={handleWfDownloadReportJson}
          />
        )}

        {tab === "regimes" && (
          <RegimePanel
            params={backtestParams}
            busy={regimeBusy}
            data={regimeData}
            sessionData={sessionData}
            error={error}
            onRun={handleRegimeRun}
            onRunSession={handleSessionRun}
          />
        )}

        {tab === "portfolio" && (
          <PortfolioPanel
            params={backtestParams}
            strategies={strategies}
            busy={portfolioBusy}
            error={error}
            result={portfolioResult}
            onRun={handlePortfolioRun}
          />
        )}

        {tab === "automation" && (
          <AutomationPanel
            busy={automationBusy}
            error={error}
            tournament={tournamentResult}
            divergence={divergenceResult}
            readiness={readinessResult}
            onRunTournament={handleTournamentRun}
            onCheckDivergence={handleDivergenceCheck}
            onCheckReadiness={handleReadinessCheck}
          />
        )}

        {tab === "history" && (
          <HistoryView
            runs={runs}
            loading={runsLoading}
            activeId={
              currentSource.type === "run" ? currentSource.id : null
            }
            selectedIds={selectedRunIds}
            onToggleSelected={handleToggleSelected}
            onClearSelection={handleClearSelection}
            onCompare={handleOpenCompare}
            compareLoading={compareLoading}
            onDeleteSelected={handleDeleteSelectedRuns}
            deleteSelectedBusy={runsDeleteBusy}
            onOpen={handleOpenRun}
            onClone={handleCloneRun}
            onDelete={handleDeleteRun}
            onRename={handleRenameRun}
            onRefresh={refreshRuns}
            onSaveAsProfile={(run, name, desc) =>
              saveProfileFrom({ kind: "run", run }, name, desc)
            }
          />
        )}

        {tab === "compare" && (
          <CompareView
            payloads={comparePayloads}
            onOpen={handleOpenRun}
            onRemove={(id) =>
              setComparePayloads((prev) => prev.filter((p) => p.meta.id !== id))
            }
            onGoToHistory={() => setTab("history")}
          />
        )}

        {tab === "profiles" && (
          <ProfilesView
            profiles={profiles}
            loading={profilesLoading}
            onRefresh={refreshProfiles}
            onLoadFull={handleLoadProfileFull}
            onLoadIntoBacktest={handleLoadProfileIntoBacktest}
            onCreateVersion={handleCreateProfileVersion}
            onEditDescription={handleEditProfileDescription}
            onAppendChangelog={handleAppendProfileChangelog}
            onDelete={handleDeleteProfile}
            onRebaselineWalkforward={handleRebaselineProfilesWalkforward}
          />
        )}

        {tab === "help" && (
          <HelpPanel onNavigateTab={setTab} />
        )}
      </main>
    </div>
  );
}

// =====================================================================
// Tab views
// =====================================================================

function CurrentView({
  data,
  currentSource,
  filterParams,
  onSwitchSource,
}: {
  data: DashboardData | null;
  currentSource: CurrentSource;
  filterParams: StrategyParams | null;
  onSwitchSource: (s: CurrentSource) => void;
}) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/40 p-3 text-xs">
        <span className="text-slate-500">Source:</span>
        <SourceButton
          active={currentSource.type === "live"}
          onClick={() => onSwitchSource({ type: "live" })}
        >
          Live
        </SourceButton>
        <SourceButton
          active={currentSource.type === "backtest"}
          onClick={() => onSwitchSource({ type: "backtest" })}
        >
          Latest backtest
        </SourceButton>
        {currentSource.type === "run" && (
          <SourceButton active onClick={() => {}}>
            Run · {currentSource.label}
          </SourceButton>
        )}
      </div>

      <OptInFiltersContext params={filterParams} />

      {data ? (
        <>
          <MetricsCards data={data} />
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <EquityCurveChart
                equity={data.equity_history}
                initialBalance={data.initial_balance}
              />
            </div>
            <PositionCard data={data} />
          </div>
          <TradeTable trades={data.trades} />
        </>
      ) : (
        <div className="py-24 text-center text-slate-500">Loading…</div>
      )}
    </div>
  );
}

function SourceButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "rounded-md px-3 py-1 font-medium transition-colors " +
        (active
          ? "bg-slate-700 text-slate-100"
          : "text-slate-400 hover:text-slate-200")
      }
    >
      {children}
    </button>
  );
}

function BacktestView({
  params,
  strategies,
  symbols,
  defaults,
  onChange,
  onRun,
  busy,
  last,
  profiles,
  profilesLoading,
  activeProfile,
  onApplyProfile,
  onSaveProfile,
  onDeleteProfile,
  onRefreshProfiles,
}: {
  params: StrategyParams | null;
  strategies: StrategyInfo[];
  symbols: string[];
  defaults: StrategyParams | null;
  onChange: (p: StrategyParams) => void;
  onRun: () => void;
  busy: boolean;
  last: BacktestRunResponse | null;
  profiles: ProfileMeta[];
  profilesLoading: boolean;
  activeProfile: string | null;
  onApplyProfile: (name: string) => void;
  onSaveProfile: (name: string, description: string) => void;
  onDeleteProfile: (name: string) => void;
  onRefreshProfiles: () => void;
}) {
  if (!params || !defaults) {
    return (
      <div className="py-12 text-center text-sm text-slate-500">
        Loading defaults…
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
        <div className="mb-4 flex items-center justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold">Configure backtest</h2>
            <p className="text-xs text-slate-500">
              Runs against the chosen symbol+timeframe over the last N bars,
              saves the result to History.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onChange(defaults)}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
            >
              Reset
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onRun}
              className="rounded-md bg-slate-200 px-4 py-1.5 text-sm font-semibold text-slate-950 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "Running…" : "Run backtest"}
            </button>
          </div>
        </div>
        <div className="mb-4">
          <ProfileBar
            profiles={profiles}
            loading={profilesLoading}
            activeName={activeProfile}
            disabled={busy}
            onApply={onApplyProfile}
            onSave={onSaveProfile}
            onDelete={onDeleteProfile}
            onRefresh={onRefreshProfiles}
          />
        </div>
        <StrategyForm
          params={params}
          strategies={strategies}
          symbols={symbols}
          onChange={onChange}
          disabled={busy}
        />
      </div>

      {last && (
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            Last backtest summary
          </div>
          <SummaryTable
            summary={last.summary as unknown as Record<string, unknown>}
          />
          {last.saved && (
            <div className="mt-3 text-xs text-slate-500">
              Saved as <span className="text-slate-300">{last.saved.label}</span>{" "}
              · <code className="text-slate-400">{last.saved.id}</code>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SummaryTable({ summary }: { summary: Record<string, unknown> }) {
  const order = [
    "trades",
    "wins",
    "losses",
    "win_rate",
    "return_pct",
    "total_pnl",
    "gross_pnl",
    "fees_paid",
    "balance",
    "skipped_by_cooldown",
    "timeframe",
    "bars",
  ];
  const keys = order.filter((k) => k in summary);
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 font-mono text-xs sm:grid-cols-3 md:grid-cols-4">
      {keys.map((k) => (
        <div key={k} className="flex justify-between gap-2">
          <span className="text-slate-500">{k}</span>
          <span className="text-slate-200">{formatSummaryValue(summary[k])}</span>
        </div>
      ))}
    </div>
  );
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

/**
 * Strict equality over two StrategyParams objects. Used to decide
 * whether the lastBacktest summary still applies to the current form
 * state (any hand-edit invalidates the cached summary). Comparing all
 * known keys rather than just identifying ones avoids "stats look
 * right but filters have silently changed" pitfalls.
 */
function paramsEqual(a: StrategyParams, b: StrategyParams): boolean {
  const keys = new Set<string>([
    ...(Object.keys(a) as string[]),
    ...(Object.keys(b) as string[]),
  ]);
  for (const k of keys) {
    if (
      (a as unknown as Record<string, unknown>)[k] !==
      (b as unknown as Record<string, unknown>)[k]
    ) {
      return false;
    }
  }
  return true;
}

function LiveView({
  params,
  strategies,
  symbols,
  defaults,
  onChange,
  status,
  busy,
  onStart,
  onStop,
  profiles,
  profilesLoading,
  activeProfile,
  onApplyProfile,
  onSaveProfile,
  onDeleteProfile,
  onRefreshProfiles,
}: {
  params: StrategyParams | null;
  strategies: StrategyInfo[];
  symbols: string[];
  defaults: StrategyParams | null;
  onChange: (p: StrategyParams) => void;
  status: LiveStatus | null;
  busy: boolean;
  onStart: () => void;
  onStop: () => void;
  profiles: ProfileMeta[];
  profilesLoading: boolean;
  activeProfile: string | null;
  onApplyProfile: (name: string) => void;
  onSaveProfile: (name: string, description: string) => void;
  onDeleteProfile: (name: string) => void;
  onRefreshProfiles: () => void;
}) {
  if (!params || !defaults) {
    return (
      <div className="py-12 text-center text-sm text-slate-500">
        Loading defaults…
      </div>
    );
  }
  const running = status?.running ?? false;
  return (
    <div className="space-y-6">
      <LiveControls
        status={status}
        canStart={!!params}
        busy={busy}
        onStart={onStart}
        onStop={onStop}
      />

      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
        <div className="mb-4 flex items-center justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold">
              {running ? "Running configuration" : "Configure live bot"}
            </h2>
            <p className="text-xs text-slate-500">
              {running
                ? "Stop the bot to change any of these."
                : "The bot will paper-trade this config until you stop it. On stop, the session is saved to History."}
            </p>
          </div>
          {!running && (
            <button
              type="button"
              onClick={() => onChange(defaults)}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
            >
              Reset
            </button>
          )}
        </div>
        <div className="mb-4">
          <ProfileBar
            profiles={profiles}
            loading={profilesLoading}
            activeName={activeProfile}
            disabled={running || busy}
            onApply={onApplyProfile}
            onSave={onSaveProfile}
            onDelete={onDeleteProfile}
            onRefresh={onRefreshProfiles}
          />
        </div>
        <StrategyForm
          params={running && status?.params ? status.params : params}
          strategies={strategies}
          symbols={symbols}
          onChange={onChange}
          disabled={running || busy}
        />
      </div>
    </div>
  );
}

const HISTORY_PAGE_SIZE = 15;

function HistoryView({
  runs,
  loading,
  activeId,
  selectedIds,
  onToggleSelected,
  onClearSelection,
  onCompare,
  compareLoading,
  onDeleteSelected,
  deleteSelectedBusy,
  onOpen,
  onClone,
  onDelete,
  onRename,
  onRefresh,
  onSaveAsProfile,
}: {
  runs: RunMeta[];
  loading: boolean;
  activeId: string | null;
  selectedIds: Set<string>;
  onToggleSelected: (id: string) => void;
  onClearSelection: () => void;
  onCompare: () => void;
  compareLoading: boolean;
  onDeleteSelected: () => void;
  deleteSelectedBusy: boolean;
  onOpen: (id: string) => void;
  onClone: (run: RunMeta) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, label: string) => void;
  onRefresh: () => void;
  onSaveAsProfile: (run: RunMeta, name: string, description: string) => void;
}) {
  const [page, setPage] = useState(0);
  const total = runs.length;
  const totalPages = Math.max(1, Math.ceil(total / HISTORY_PAGE_SIZE));

  useEffect(() => {
    setPage((p) => Math.min(p, totalPages - 1));
  }, [totalPages]);

  const pageRuns = useMemo(() => {
    const start = page * HISTORY_PAGE_SIZE;
    return runs.slice(start, start + HISTORY_PAGE_SIZE);
  }, [runs, page]);

  const showingFrom = total === 0 ? 0 : page * HISTORY_PAGE_SIZE + 1;
  const showingTo = Math.min((page + 1) * HISTORY_PAGE_SIZE, total);
  const count = selectedIds.size;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">Saved runs</h2>
          <p className="text-xs text-slate-500">
            Tick the boxes to compare runs on one chart or delete several at
            once.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {count > 0 && (
            <>
              <button
                type="button"
                onClick={onClearSelection}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
              >
                Clear ({count})
              </button>
              <button
                type="button"
                onClick={onCompare}
                disabled={compareLoading || count < 1}
                className="rounded-md bg-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                {compareLoading
                  ? "Loading…"
                  : `Compare ${count} selected`}
              </button>
              <button
                type="button"
                onClick={onDeleteSelected}
                disabled={deleteSelectedBusy || count < 1}
                className="rounded-md border border-bear/40 px-3 py-1.5 text-xs text-bear hover:bg-bear/10 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {deleteSelectedBusy ? "Deleting…" : `Delete ${count} selected`}
              </button>
            </>
          )}
          <button
            type="button"
            onClick={onRefresh}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
          >
            Refresh
          </button>
        </div>
      </div>
      <RunList
        runs={pageRuns}
        loading={loading}
        activeId={activeId}
        selectedIds={selectedIds}
        onToggleSelected={onToggleSelected}
        onOpen={onOpen}
        onClone={onClone}
        onDelete={onDelete}
        onRename={onRename}
        onSaveAsProfile={onSaveAsProfile}
      />
      {!loading && total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-2.5 text-xs text-slate-400">
          <span>
            Showing {showingFrom}–{showingTo} of {total}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={page <= 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              Previous
            </button>
            <span className="tabular-nums text-slate-500">
              Page {page + 1} of {totalPages}
            </span>
            <button
              type="button"
              className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={page >= totalPages - 1}
              onClick={() =>
                setPage((p) => Math.min(totalPages - 1, p + 1))
              }
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function CompareView({
  payloads,
  onOpen,
  onRemove,
  onGoToHistory,
}: {
  payloads: RunPayload[];
  onOpen: (id: string) => void;
  onRemove: (id: string) => void;
  onGoToHistory: () => void;
}) {
  if (payloads.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-800 bg-slate-900/40 p-8 text-center text-sm text-slate-500">
        No runs selected yet.{" "}
        <button
          type="button"
          className="text-slate-300 hover:underline"
          onClick={onGoToHistory}
        >
          Go to History
        </button>{" "}
        and tick the ones you want to compare.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <EquityOverlayChart runs={payloads} />
      <CompareTable payloads={payloads} onOpen={onOpen} onRemove={onRemove} />
    </div>
  );
}

function CompareTable({
  payloads,
  onOpen,
  onRemove,
}: {
  payloads: RunPayload[];
  onOpen: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  const rows = payloads.map((p) => {
    const trades = p.data.trades ?? [];
    const wins = trades.filter((t) => t.profit > 0).length;
    const winRate = trades.length ? (wins / trades.length) * 100 : 0;
    const returnPct = p.meta.summary?.return_pct ?? 0;
    const maxDrawdown =
      p.meta.summary?.max_drawdown_pct ??
      computeMaxDrawdownPct(p.data.equity_history ?? []);
    const profitFactor = p.meta.summary?.profit_factor ?? 0;
    const sharpe = p.meta.summary?.trade_sharpe ?? 0;
    return {
      id: p.meta.id,
      label: p.meta.label,
      kind: p.meta.kind,
      strategy: p.meta.params.strategy,
      market: `${p.meta.params.symbol} · ${p.meta.params.timeframe}`,
      sizing: formatSizing(p.meta.params),
      trades: trades.length,
      wins,
      winRate,
      returnPct,
      maxDrawdown,
      profitFactor,
      sharpe,
      balance: p.data.balance,
    };
  });

  return (
    <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/40">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-900/80 text-xs uppercase tracking-wider text-slate-500">
          <tr>
            <th className="px-4 py-2 font-medium">Label</th>
            <th className="px-4 py-2 font-medium">Strategy</th>
            <th className="px-4 py-2 font-medium">Market</th>
            <th className="px-4 py-2 font-medium" title="Position sizing + SL/TP mode">
              Sizing
            </th>
            <th className="px-4 py-2 text-right font-medium">Trades</th>
            <th className="px-4 py-2 text-right font-medium">Win rate</th>
            <th className="px-4 py-2 text-right font-medium">Return</th>
            <th className="px-4 py-2 text-right font-medium">Max DD</th>
            <th className="px-4 py-2 text-right font-medium" title="sum(wins)/|sum(losses)|">
              PF
            </th>
            <th className="px-4 py-2 text-right font-medium" title="per-trade mean/stdev (not annualised)">
              Sharpe
            </th>
            <th className="px-4 py-2 text-right font-medium">Balance</th>
            <th className="px-4 py-2" />
          </tr>
        </thead>
        <tbody className="font-mono">
          {rows.map((r) => (
            <tr
              key={r.id}
              className="border-t border-slate-800/60 hover:bg-slate-800/40"
            >
              <td className="px-4 py-2">
                <button
                  type="button"
                  className="text-left text-slate-200 hover:underline"
                  onClick={() => onOpen(r.id)}
                >
                  {r.label}
                </button>
              </td>
              <td className="px-4 py-2 text-slate-400">{r.strategy}</td>
              <td className="px-4 py-2 text-slate-400">{r.market}</td>
              <td className="px-4 py-2">
                <SizingBadge sizing={r.sizing} />
              </td>
              <td className="px-4 py-2 text-right text-slate-300">{r.trades}</td>
              <td className="px-4 py-2 text-right text-slate-300">
                {r.winRate.toFixed(1)}%
              </td>
              <td
                className={
                  "px-4 py-2 text-right font-medium " +
                  (r.returnPct > 0
                    ? "text-bull"
                    : r.returnPct < 0
                    ? "text-bear"
                    : "text-slate-400")
                }
              >
                {r.returnPct > 0 ? "+" : ""}
                {r.returnPct.toFixed(2)}%
              </td>
              <td className="px-4 py-2 text-right text-slate-300">
                {r.maxDrawdown.toFixed(2)}%
              </td>
              <td className="px-4 py-2 text-right text-slate-300">
                {r.profitFactor >= 999
                  ? "∞"
                  : r.profitFactor.toFixed(2)}
              </td>
              <td className="px-4 py-2 text-right text-slate-300">
                {r.sharpe.toFixed(2)}
              </td>
              <td className="px-4 py-2 text-right text-slate-300">
                {formatCurrency(r.balance)}
              </td>
              <td className="px-4 py-2 text-right">
                <button
                  type="button"
                  className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800"
                  onClick={() => onRemove(r.id)}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function computeMaxDrawdownPct(
  equity: { balance: number }[]
): number {
  let peak = -Infinity;
  let maxDD = 0;
  for (const p of equity) {
    if (p.balance > peak) peak = p.balance;
    if (peak > 0) {
      const dd = ((peak - p.balance) / peak) * 100;
      if (dd > maxDD) maxDD = dd;
    }
  }
  return maxDD;
}

type SizingInfo =
  | { mode: "atr"; risk: number; stopMult: number; tpMult: number }
  | { mode: "fixed"; stopPct: number; tpPct: number };

/** Condense how a run sized its trades, for at-a-glance compare. */
function formatSizing(params: StrategyParams): SizingInfo {
  if (params.use_atr_sizing) {
    return {
      mode: "atr",
      risk: params.atr_risk_pct ?? 0,
      stopMult: params.atr_stop_mult ?? 0,
      tpMult: params.atr_tp_mult ?? 0,
    };
  }
  return {
    mode: "fixed",
    stopPct: params.stop_loss_pct ?? 0,
    tpPct: params.take_profit_pct ?? 0,
  };
}

function SizingBadge({ sizing }: { sizing: SizingInfo }) {
  if (sizing.mode === "atr") {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-md bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300"
        title={`ATR-based: ${(sizing.risk * 100).toFixed(2)}% risk, SL=${sizing.stopMult}×ATR, TP=${sizing.tpMult}×ATR`}
      >
        <span className="font-semibold">ATR</span>
        <span className="tabular-nums">
          {sizing.stopMult}×/{sizing.tpMult}×
        </span>
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md bg-slate-700/50 px-2 py-0.5 text-[10px] font-medium text-slate-300"
      title={`Fixed: SL=${(sizing.stopPct * 100).toFixed(2)}%, TP=${(sizing.tpPct * 100).toFixed(2)}%`}
    >
      <span>Fixed</span>
      <span className="tabular-nums">
        {(sizing.stopPct * 100).toFixed(1)}%/{(sizing.tpPct * 100).toFixed(1)}%
      </span>
    </span>
  );
}
