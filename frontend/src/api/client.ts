import type { components, paths } from './schema';

export type Health = components['schemas']['Health'];
export type Direction = components['schemas']['Direction'];
export type Instrument = components['schemas']['Instrument'];
export type InstrumentList = components['schemas']['InstrumentList'];
export type PriceBar = components['schemas']['PriceBar'];
export type PriceBarList = components['schemas']['PriceBarList'];
export type Signal = components['schemas']['Signal'];
export type SignalList = components['schemas']['SignalList'];

export type SignalQuery = NonNullable<paths['/signals']['get']['parameters']['query']>;
export type PriceQuery = NonNullable<
  paths['/instruments/{symbol}/prices']['get']['parameters']['query']
>;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

async function request<T>(
  path: string,
  query?: Record<string, string | number | undefined>,
): Promise<T> {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== '') {
        url.searchParams.set(key, String(value));
      }
    }
  }

  let response: Response;
  try {
    response = await fetch(url.toString(), { headers: { Accept: 'application/json' } });
  } catch {
    throw new ApiError(0, `Backend unreachable at ${BASE_URL}`);
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as components['schemas']['Error'];
      if (body.detail) detail = body.detail;
    } catch {
      // keep the generic message
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}

export function getHealth(): Promise<Health> {
  return request<Health>('/health');
}

export function listInstruments(): Promise<InstrumentList> {
  return request<InstrumentList>('/instruments');
}

export function getPrices(symbol: string, start?: string, end?: string): Promise<PriceBarList> {
  const query: PriceQuery = { start_date: start, end_date: end };
  return request<PriceBarList>(`/instruments/${encodeURIComponent(symbol)}/prices`, query);
}

export function listSignals(filters: SignalQuery = {}): Promise<SignalList> {
  return request<SignalList>('/signals', { ...filters });
}

// --- Model catalog and experiment runs (feature 005) ----------------------

export type ParamSpec = components['schemas']['ParamSpec'];
export type Model = components['schemas']['Model'];
export type ModelList = components['schemas']['ModelList'];
export type RunRequest = components['schemas']['RunRequest'];
export type Run = components['schemas']['Run'];
export type RunList = components['schemas']['RunList'];
export type RunDetail = components['schemas']['RunDetail'];
export type ExperimentSignal = components['schemas']['ExperimentSignal'];

async function send<T>(
  path: string,
  method: 'POST' | 'PATCH' | 'DELETE',
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin);
  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method,
      signal,
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, `Backend unreachable at ${BASE_URL}`);
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload.detail) detail = String(payload.detail);
    } catch {
      // keep the generic message
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function listModels(): Promise<ModelList> {
  return request<ModelList>('/models');
}

export function createRun(body: RunRequest, signal?: AbortSignal): Promise<Run> {
  return send<Run>('/runs', 'POST', body, signal);
}

export function listRuns(savedOnly = false): Promise<RunList> {
  return request<RunList>('/runs', { saved_only: savedOnly ? 'true' : undefined });
}

export function getRun(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/runs/${encodeURIComponent(runId)}`);
}

export function saveRun(runId: string, name: string): Promise<Run> {
  return send<Run>(`/runs/${encodeURIComponent(runId)}`, 'PATCH', { name });
}

export function deleteRun(runId: string): Promise<void> {
  return send<void>(`/runs/${encodeURIComponent(runId)}`, 'DELETE');
}

// --- Run performance (Quant Lab) -------------------------------------------
// Derived figures come from the backend, never from the browser: the frontend
// must not embed analytical computation (Constitution V).

export type EquityPoint = components['schemas']['EquityPoint'];
export type Trade = components['schemas']['Trade'];
export type PerformanceMetrics = components['schemas']['PerformanceMetrics'];
export type RunPerformance = components['schemas']['RunPerformance'];

export function getRunPerformance(runId: string): Promise<RunPerformance> {
  return request<RunPerformance>(`/runs/${encodeURIComponent(runId)}/performance`);
}
