import { getToken, reportUnauthorized } from '../auth/session';
import type { components, paths } from './schema';
import type {
  AuthSession,
  AuthUser,
  Credentials,
  CompanyOverview,
  ExecutionConfig,
  FundamentalFact,
  FundamentalsCoverage,
  HealthV2,
  RawCatalogModel,
  RunDetailV2,
  RunPerformanceV2,
  RunListV2,
  RunV2,
  ScreenConstraint,
  ScreenMetric,
  ScreenResult,
  Strategy,
  StrategyList,
  StrategyRunRequest,
  StrategySpec,
  StrategyTemplateList,
} from './types';

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

/**
 * Every request carries the bearer token when there is one.
 *
 * Attached here rather than at each call site: a route that forgets the header
 * does not fail loudly, it quietly reads somebody else's empty world, and that
 * is exactly the bug §1 of the contract exists to close.
 */
function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = getToken();
  return {
    Accept: 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
}

/**
 * A 401 means the stored token is no longer a session. Dropping it here — one
 * place, idempotently — is what makes the shell fall back to the login screen
 * without every caller having to know that a redirect exists.
 *
 * `anonymous` requests (login, register) opt out: a 401 there is "those
 * credentials are wrong", not "your session died", and must not log out the
 * user who was already signed in.
 */
function noteUnauthorized(status: number, anonymous: boolean): void {
  if (status === 401 && !anonymous) reportUnauthorized();
}

async function detailFrom(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (body.detail) return String(body.detail);
  } catch {
    // keep the generic message
  }
  return `Request failed with status ${response.status}`;
}

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
    response = await fetch(url.toString(), { headers: authHeaders() });
  } catch {
    throw new ApiError(0, `Backend unreachable at ${BASE_URL}`);
  }

  if (!response.ok) {
    noteUnauthorized(response.status, false);
    throw new ApiError(response.status, await detailFrom(response));
  }

  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthV2> {
  return request<HealthV2>('/health');
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
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  body?: unknown,
  signal?: AbortSignal,
  /** True for the credential endpoints, whose 401 is not a dead session. */
  anonymous = false,
): Promise<T> {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin);
  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method,
      signal,
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, `Backend unreachable at ${BASE_URL}`);
  }

  if (!response.ok) {
    noteUnauthorized(response.status, anonymous);
    throw new ApiError(response.status, await detailFrom(response));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** `/models` after §2: the same items, plus category, summary and roles. */
export interface CatalogModelList {
  total: number;
  items: RawCatalogModel[];
}

export function listModels(): Promise<CatalogModelList> {
  return request<CatalogModelList>('/models');
}

export function createRun(body: RunRequest, signal?: AbortSignal): Promise<Run> {
  return send<Run>('/runs', 'POST', body, signal);
}

export function listRuns(savedOnly = false): Promise<RunListV2> {
  return request<RunListV2>('/runs', { saved_only: savedOnly ? 'true' : undefined });
}

export function getRun(runId: string): Promise<RunDetailV2> {
  return request<RunDetailV2>(`/runs/${encodeURIComponent(runId)}`);
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

/**
 * Typed as the §5 shape: the same endpoint, with per-trade side, quantity,
 * exit reason, P&L and fees, plus the cost totals and exit-reason breakdown.
 * Every addition is optional, so a run recorded before the change still reads.
 */
export function getRunPerformance(runId: string): Promise<RunPerformanceV2> {
  return request<RunPerformanceV2>(`/runs/${encodeURIComponent(runId)}/performance`);
}

// --- Identity (contract v2 §1) ---------------------------------------------
// The credential endpoints are `anonymous`: their 401 means "wrong email or
// password" and must not tear down a session that is still valid.

export function register(credentials: Credentials): Promise<AuthSession> {
  return send<AuthSession>('/auth/register', 'POST', credentials, undefined, true);
}

export function login(credentials: Credentials): Promise<AuthSession> {
  return send<AuthSession>('/auth/login', 'POST', credentials, undefined, true);
}

export function logout(): Promise<void> {
  return send<void>('/auth/logout', 'POST');
}

export function getMe(): Promise<AuthUser> {
  return request<AuthUser>('/auth/me');
}

// --- Strategies (contract v2 §3) -------------------------------------------

export function listStrategies(): Promise<StrategyList> {
  return request<StrategyList>('/strategies');
}

export function createStrategy(spec: StrategySpec): Promise<Strategy> {
  return send<Strategy>('/strategies', 'POST', spec);
}

export function getStrategy(id: string): Promise<Strategy> {
  return request<Strategy>(`/strategies/${encodeURIComponent(id)}`);
}

/** PUT, not PATCH: §3 replaces the spec, so a dropped component really drops. */
export function replaceStrategy(id: string, spec: StrategySpec): Promise<Strategy> {
  return send<Strategy>(`/strategies/${encodeURIComponent(id)}`, 'PUT', spec);
}

export function deleteStrategy(id: string): Promise<void> {
  return send<void>(`/strategies/${encodeURIComponent(id)}`, 'DELETE');
}

/**
 * The starter strategies, from the server rather than from a table in the
 * frontend. Unauthenticated, and identical for everyone.
 *
 * They live there because only the registry knows which rules actually exist:
 * a template hardcoded here would name a rule this deployment might not have
 * registered, and would 422 on save with nothing useful to say about why.
 */
export function listStrategyTemplates(): Promise<StrategyTemplateList> {
  return request<StrategyTemplateList>('/strategy-templates');
}

// --- Strategy-shaped runs (contract v2 §5) ---------------------------------

/**
 * The same `POST /runs`, given the strategy body instead of the legacy one.
 * Exactly one of `strategy_id` and `strategy` may be set; the server answers
 * 400 otherwise, and the builder never sends both.
 */
export function createStrategyRun(body: StrategyRunRequest, signal?: AbortSignal): Promise<RunV2> {
  return send<RunV2>('/runs', 'POST', body, signal);
}

// --- Fundamentals (docs/FUNDAMENTALS.md) -----------------------------------

/**
 * What one instrument's filings said, as of a date.
 *
 * The as-of date is the whole request: the server answers with rows whose
 * `filed_at <= as_of`, which is the only reading of the table that does not
 * use a document from the future to trade in the past (§2). Sending the date
 * rather than filtering here is deliberate — a browser-side cut on a full
 * history would be a second implementation of the rule.
 *
 * The response is accepted both as a bare array and as the `{ total, items }`
 * envelope the rest of the API uses: both are plausible from a backend still
 * being written, and neither is worth a crash.
 */
export async function getFundamentals(symbol: string, asOf: string): Promise<FundamentalFact[]> {
  const body = await request<FundamentalFact[] | { items?: FundamentalFact[] }>(
    `/instruments/${encodeURIComponent(symbol)}/fundamentals`,
    { as_of: asOf },
  );
  return Array.isArray(body) ? body : (body.items ?? []);
}

/**
 * Which instruments and concepts have any fundamentals at all.
 *
 * Read once and held: it is a property of the warehouse, not of the strategy
 * being edited, and re-reading it on every component added would put a network
 * round trip inside a keystroke.
 */
export function getFundamentalsCoverage(): Promise<FundamentalsCoverage> {
  return request<FundamentalsCoverage>('/fundamentals/coverage');
}

// --- Research (docs/RESEARCH.md) -------------------------------------------

/**
 * Everything filed about one name, as of a date.
 *
 * One request rather than the four it composes. The company page needs price
 * bounds, the point-in-time accounts, coverage and signal history to render at
 * all, and issuing those separately would paint the panel in four stages, each
 * with its own failure — a page that is half-wrong for a moment is worse than
 * one that is briefly empty.
 */
export function getCompanyOverview(symbol: string, asOf?: string): Promise<CompanyOverview> {
  return request<CompanyOverview>(
    `/instruments/${encodeURIComponent(symbol)}/overview`,
    asOf ? { as_of: asOf } : {},
  );
}

/**
 * Narrow a universe by filed ratios.
 *
 * `universe` is required by the index, not by taste: `fundamentals_pit_idx`
 * leads with `instrument_id`, so an unbounded screen falls to a sequential
 * scan and takes 6.7s against 836ms bounded (docs/RESEARCH.md §2). Screening
 * within a named list is also what the work actually is.
 */
export function screen(params: {
  universe: string;
  constraints?: ScreenConstraint[];
  metrics?: ScreenMetric[];
  asOf?: string;
  sortBy?: ScreenMetric;
  descending?: boolean;
  limit?: number;
}): Promise<ScreenResult> {
  const query: Record<string, string> = { universe: params.universe };
  if (params.asOf) query.as_of = params.asOf;
  if (params.sortBy) query.sort_by = params.sortBy;
  if (params.descending !== undefined) query.descending = String(params.descending);
  if (params.limit !== undefined) query.limit = String(params.limit);
  if (params.metrics?.length) query.metrics = params.metrics.join(',');
  // Constraints go over as `metric:min:max`, empty bound meaning unbounded, so
  // the whole screen stays a GET and therefore stays linkable and cacheable.
  if (params.constraints?.length) {
    query.constraints = params.constraints
      .map((c) => `${c.metric}:${c.min ?? ''}:${c.max ?? ''}`)
      .join(',');
  }
  return request<ScreenResult>('/screen', query);
}

/** The universes a screen may be run over. */
export function listUniverses(): Promise<{ items: { name: string; as_of: string; size: number }[] }> {
  return request<{ items: { name: string; as_of: string; size: number }[] }>('/universes');
}

export type { ExecutionConfig };
