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
