/**
 * The one HTTP client. Every request:
 *   - goes to the same-origin /api/v1 (proxied to FastAPI in dev and by nginx
 *     in the container), so no URL is ever built from user input;
 *   - carries the anonymous browser session (X-NavigIQ-Session), which the
 *     backend uses to own plans and conversations before sign-in;
 *   - carries the access token when signed in, refreshing it once on 401.
 * Errors come back as ApiError with the backend's stable `code`; screens
 * switch on the code, never on message text.
 */
import { getSessionId } from "@/lib/session";
import { tokenStore } from "@/lib/api/tokens";

export const API_BASE = "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | null;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  get isNetwork(): boolean {
    return this.status === 0;
  }
}

type Json = Record<string, unknown> | unknown[] | null;

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: Json;
  query?: Record<string, string | number | boolean | string[] | undefined | null>;
  signal?: AbortSignal;
  /** Skip the Authorization header (login, register, refresh). */
  anonymous?: boolean;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else params.set(key, String(value));
  }
  const qs = params.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function parseError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // not JSON: fall through to a generic error
  }
  const err = (body as { detail?: { error?: { code?: string; message?: string; details?: Record<string, unknown> } }; error?: { code?: string; message?: string; details?: Record<string, unknown> } } | null);
  const payload = err?.error ?? err?.detail?.error;
  if (payload?.code) {
    return new ApiError(res.status, payload.code, payload.message ?? "Request failed", payload.details ?? null);
  }
  if (res.status === 422) {
    return new ApiError(422, "VALIDATION_ERROR", "Some of the details weren't valid.");
  }
  if (res.status === 429) {
    return new ApiError(429, "RATE_LIMITED", "Too many requests — give it a moment.");
  }
  return new ApiError(res.status, `HTTP_${res.status}`, "Something went wrong on our side.");
}

let refreshing: Promise<boolean> | null = null;

/**
 * Exchange the stored refresh token for a new pair. Concurrent callers (a
 * 401 retry, the session restore on load, React's double-invoked effects)
 * share one request — the backend rotates refresh tokens, so a second
 * request with the same token would fail and sign the person out.
 * The session is cleared only when the server actually rejects the token,
 * never because the network was down.
 */
export async function refreshSession(): Promise<boolean> {
  const refresh = tokenStore.refreshToken;
  if (!refresh) return false;
  refreshing ??= (async () => {
    try {
      const res = await fetch(buildUrl("/auth/refresh"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!res.ok) {
        if (res.status === 401 || res.status === 403 || res.status === 422) tokenStore.clear();
        return false;
      }
      tokenStore.set(await res.json());
      return true;
    } catch {
      return false;
    } finally {
      // Concurrent callers already hold this promise; the next 401 starts fresh.
      refreshing = null;
    }
  })();
  return refreshing;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const doFetch = () => {
    const headers: Record<string, string> = {
      Accept: "application/json",
      "X-NavigIQ-Session": getSessionId(),
    };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    const token = opts.anonymous ? null : tokenStore.accessToken;
    if (token) headers.Authorization = `Bearer ${token}`;
    return fetch(buildUrl(path, opts.query), {
      method: opts.method ?? "GET",
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  };

  // After a reload the access token is gone but the refresh token isn't:
  // restore the session first rather than sending a request that is bound to
  // come back 401 (one round trip less, and one auth request less).
  if (!opts.anonymous && tokenStore.refreshToken && !tokenStore.accessToken) {
    await refreshSession();
  }

  let res: Response;
  try {
    res = await doFetch();
    if (res.status === 401 && !opts.anonymous && tokenStore.refreshToken) {
      if (await refreshSession()) res = await doFetch();
    }
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "NETWORK", "Can't reach NavigIQ right now. Check your connection.");
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) =>
    request<T>(path, { query, signal }),
  post: <T>(path: string, body?: Json, opts: Omit<RequestOptions, "method" | "body"> = {}) =>
    request<T>(path, { ...opts, method: "POST", body: body ?? {} }),
  put: <T>(path: string, body: Json) => request<T>(path, { method: "PUT", body }),
  del: <T>(path: string, body?: Json) => request<T>(path, { method: "DELETE", body }),
};
