import { ApiError } from './client';
import type { components } from './schema';

export type AuthCredentials = components['schemas']['AuthCredentials'];
export type User = components['schemas']['User'];
export type UserPublic = components['schemas']['UserPublic'];

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

/**
 * Auth endpoints get their own fetch wrapper on purpose: a 401 here is an
 * answer (bad credentials, no session yet), not a session expiry, so these
 * calls must never feed the reportSessionExpired collapse in client.ts.
 */
async function authRequest<T>(path: string, method: 'GET' | 'POST', body?: unknown): Promise<T> {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin);
  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method,
      headers: {
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
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

export function fetchCurrentUser(): Promise<UserPublic> {
  return authRequest<UserPublic>('/auth/me', 'GET');
}

export function login(credentials: AuthCredentials): Promise<User> {
  return authRequest<User>('/auth/login', 'POST', credentials);
}

export function register(credentials: AuthCredentials): Promise<User> {
  return authRequest<User>('/auth/register', 'POST', credentials);
}

export function logout(): Promise<void> {
  return authRequest<void>('/auth/logout', 'POST');
}
