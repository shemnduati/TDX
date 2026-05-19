import type {
  BacktestRunResponse,
  DashboardData,
  DataSource,
  LiveStatus,
  PortfolioRiskConfig,
  PortfolioRunResponse,
  ReadinessResponse,
  RegimeExpectancyResponse,
  DivergenceResponse,
  TournamentRunResponse,
  ProfileDoc,
  ProfileMeta,
  ProfilesWalkforwardRebaselineResponse,
  ProfilesWalkforwardRebaselineStart,
  RunMeta,
  RunPayload,
  SaveProfilePayload,
  UpdateProfilePayload,
  StrategyInfo,
  StrategyParams,
  SweepStart,
  SweepStatus,
  WalkforwardStart,
  WalkforwardStabilityResponse,
  WalkforwardStatus,
} from "./types";

const API = ""; // requests go to /api/... which Vite proxies to Flask

async function request<T>(
  path: string,
  init: RequestInit & { signal?: AbortSignal } = {}
): Promise<T> {
  const res = await fetch(`${API}/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* ignore */
    }
    const errMsg =
      (body && typeof body === "object" && "error" in body
        ? String((body as { error: unknown }).error)
        : null) ?? `${res.status} ${res.statusText}`;
    throw new Error(errMsg);
  }
  return (await res.json()) as T;
}

// ------------------------------------------------------------- dashboard
const ENDPOINTS: Record<DataSource, string> = {
  live: "/data",
  backtest: "/backtest",
};

export function fetchDashboardData(
  source: DataSource,
  signal?: AbortSignal
): Promise<DashboardData> {
  return request<DashboardData>(ENDPOINTS[source], { signal });
}

// -------------------------------------------------------------- metadata
export function fetchStrategies(
  signal?: AbortSignal
): Promise<{ strategies: StrategyInfo[] }> {
  return request("/strategies", { signal });
}

export function fetchSymbols(
  signal?: AbortSignal
): Promise<{ symbols: string[] }> {
  return request("/symbols", { signal });
}

export function fetchDefaults(
  signal?: AbortSignal
): Promise<StrategyParams> {
  return request("/config/defaults", { signal });
}

// -------------------------------------------------------------- backtest
export function runBacktest(
  params: StrategyParams,
  opts: { label?: string; save?: boolean } = {}
): Promise<BacktestRunResponse> {
  return request<BacktestRunResponse>("/backtest/run", {
    method: "POST",
    body: JSON.stringify({
      params,
      label: opts.label,
      save: opts.save ?? true,
    }),
  });
}

// ------------------------------------------------------------------ runs
export function listRuns(
  signal?: AbortSignal
): Promise<{ runs: RunMeta[] }> {
  return request("/runs", { signal });
}

export function loadRun(
  id: string,
  signal?: AbortSignal
): Promise<RunPayload> {
  return request(`/runs/${encodeURIComponent(id)}`, { signal });
}

export function deleteRun(id: string): Promise<{ deleted: boolean }> {
  return request(`/runs/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function renameRun(id: string, label: string): Promise<RunMeta> {
  return request(`/runs/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ label }),
  });
}

// ------------------------------------------------------------------ live
export function liveStatus(signal?: AbortSignal): Promise<LiveStatus> {
  return request("/live/status", { signal });
}

export function liveStart(params: StrategyParams): Promise<LiveStatus> {
  return request("/live/start", {
    method: "POST",
    body: JSON.stringify({ params }),
  });
}

export function liveStop(
  opts: { save?: boolean; label?: string } = {}
): Promise<LiveStatus> {
  return request("/live/stop", {
    method: "POST",
    body: JSON.stringify({ save: opts.save ?? true, label: opts.label }),
  });
}

// ---------------------------------------------------------------- sweep
export function sweepStatus(signal?: AbortSignal): Promise<SweepStatus> {
  return request("/sweep/status", { signal });
}

export function sweepStart(body: SweepStart): Promise<SweepStatus> {
  return request("/sweep/start", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function sweepCancel(): Promise<SweepStatus> {
  return request("/sweep/cancel", { method: "POST" });
}

// -------------------------------------------------------- walk-forward
export function walkforwardStatus(
  signal?: AbortSignal
): Promise<WalkforwardStatus> {
  return request("/walkforward/status", { signal });
}

export function walkforwardStart(
  body: WalkforwardStart
): Promise<WalkforwardStatus> {
  return request("/walkforward/start", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function walkforwardCancel(): Promise<WalkforwardStatus> {
  return request("/walkforward/cancel", { method: "POST" });
}

export function walkforwardStability(
  signal?: AbortSignal
): Promise<WalkforwardStabilityResponse> {
  return request("/walkforward/stability", { signal });
}

export async function downloadWalkforwardStabilityCsv(): Promise<void> {
  const res = await fetch(`${API}/api/walkforward/stability.csv`);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "walkforward_stability.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function downloadWalkforwardWindowsCsv(): Promise<void> {
  const res = await fetch(`${API}/api/walkforward/windows.csv`);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "walkforward_windows.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function downloadWalkforwardReportJson(): Promise<void> {
  const res = await fetch(`${API}/api/walkforward/report.json`);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "walkforward_report.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// -------------------------------------------------------------- regime
export function regimeExpectancy(
  body: { params: Partial<StrategyParams>; strategies?: string[] }
): Promise<RegimeExpectancyResponse> {
  return request("/regime/expectancy", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function portfolioRun(body: {
  params: Partial<StrategyParams>;
  weights: Record<string, number>;
  risk?: Partial<PortfolioRiskConfig>;
}): Promise<PortfolioRunResponse> {
  return request("/portfolio/run", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function tournamentRun(body: {
  profiles?: string[];
  train_bars?: number;
  test_bars?: number;
  step?: number;
  mc_sims?: number;
  train_engine?: "grid" | "optuna";
  optuna_trials?: number;
  optuna_seed?: number;
  min_pos_rate?: number;
  min_oos_ret?: number;
  dry_run?: boolean;
}): Promise<TournamentRunResponse> {
  return request("/tournament/run", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function monitorDivergence(body: {
  run_id?: string;
  compare_bars?: number;
  thresholds?: Record<string, number>;
} = {}): Promise<DivergenceResponse> {
  return request("/monitor/divergence", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function monitorReadiness(body: {
  days?: number;
  min_aligned_pct?: number;
  min_samples?: number;
  compare_bars?: number;
  thresholds?: Record<string, number>;
  min_avg_timestamp_match_rate?: number;
  max_avg_mean_abs_pnl_delta_pct?: number;
} = {}): Promise<ReadinessResponse> {
  return request("/monitor/readiness", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// -------------------------------------------------------------- profiles
// Named parameter presets persisted to disk on the backend. The list
// endpoint returns lightweight summaries; only fetch the full params
// payload when the user actually applies a profile.

export function listProfiles(
  signal?: AbortSignal
): Promise<{ profiles: ProfileMeta[] }> {
  return request("/profiles", { signal });
}

export function getProfile(
  name: string,
  signal?: AbortSignal
): Promise<ProfileDoc> {
  return request(`/profiles/${encodeURIComponent(name)}`, { signal });
}

export function saveProfile(
  body: SaveProfilePayload
): Promise<{ saved: ProfileDoc; path: string }> {
  return request("/profiles", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateProfile(
  name: string,
  body: UpdateProfilePayload
): Promise<{ saved: ProfileDoc }> {
  return request(`/profiles/${encodeURIComponent(name)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteProfile(
  name: string
): Promise<{ deleted: boolean }> {
  return request(`/profiles/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export function rebaselineProfilesWalkforward(
  body: ProfilesWalkforwardRebaselineStart
): Promise<ProfilesWalkforwardRebaselineResponse> {
  return request("/profiles/rebaseline/walkforward", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
