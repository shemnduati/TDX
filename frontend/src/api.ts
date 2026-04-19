import type {
  BacktestRunResponse,
  DashboardData,
  DataSource,
  LiveStatus,
  ProfileDoc,
  ProfileMeta,
  RunMeta,
  RunPayload,
  SaveProfilePayload,
  UpdateProfilePayload,
  StrategyInfo,
  StrategyParams,
  SweepStart,
  SweepStatus,
  WalkforwardStart,
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
