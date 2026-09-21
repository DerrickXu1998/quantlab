import { ApiError } from '../api/client';
import type { components } from '../api/schema';

/**
 * The fetch plumbing for modules that cannot live in src/api (that directory
 * is regenerated). Same behavior as api/client's private helpers: ApiError on
 * unreachable/non-OK, detail lifted from the error payload.
 */

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

type Query = Record<string, string | number | undefined>;

function toUrl(path: string, query?: Query): string {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== '') url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function detail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as components['schemas']['Error'];
    if (body.detail) return body.detail;
  } catch {
    // keep the generic message
  }
  return `Request failed with status ${response.status}`;
}

export async function apiGet<T>(path: string, query?: Query): Promise<T> {
  let response: Response;
  try {
    response = await fetch(toUrl(path, query), { headers: { Accept: 'application/json' } });
  } catch {
    throw new ApiError(0, `Backend unreachable at ${BASE_URL}`);
  }
  if (!response.ok) throw new ApiError(response.status, await detail(response));
  return (await response.json()) as T;
}

export async function apiSend<T>(
  path: string,
  method: 'POST' | 'PATCH' | 'DELETE',
  body?: unknown,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(toUrl(path), {
      method,
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, `Backend unreachable at ${BASE_URL}`);
  }
  if (!response.ok) throw new ApiError(response.status, await detail(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
