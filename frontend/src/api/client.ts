import type {
  ApiError, Category, FieldIssue, PlanResponse, PoiDetail, PoiSummary,
  ProfilePatch, ResolveResult, SavedPlan, SavedPlanSummary, TripSpec, UserMe,
} from "../types";

// Relative: Vite proxies /api to the backend (see vite.config.ts).
const BASE = "/api/v1";

// The login token. Kept in localStorage so a refresh keeps you signed in.
// (An httpOnly cookie would be safer against injected scripts - a later
// hardening step; it needs the backend to set the cookie.)
const TOKEN_KEY = "navigiq.token";

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* storage unavailable */ }
}

let onUnauthorized: (() => void) | null = null;

/** Called when the server rejects the token - it expired or was revoked. */
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

/** Any failed request. Carries the backend's stable error code. */
export class PlanError extends Error {
  code: ApiError["code"];
  details: ApiError["details"];

  constructor(err: ApiError) {
    super(err.message);
    this.name = "PlanError";
    this.code = err.code;
    this.details = err.details ?? null;
  }
}

function toApiError(res: Response, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;

  // NavigIQ's own error envelope: { detail: { error: { code, message, details } } }
  if (detail && typeof detail === "object" && !Array.isArray(detail) && "error" in detail) {
    return (detail as { error: ApiError }).error;
  }

  // A plain message, e.g. "Incorrect email or password".
  if (typeof detail === "string") {
    return {
      code: res.status === 400 || res.status === 401 ? "AUTH" : "UNKNOWN",
      message: detail,
    };
  }

  // FastAPI's request validation: { detail: [ { loc, msg } ] }
  if (Array.isArray(detail)) {
    const errors: FieldIssue[] = detail.map((d: { loc?: unknown[]; msg?: string }) => ({
      field: (d.loc ?? []).slice(1).join("."),
      message: d.msg ?? "Invalid value",
    }));
    return {
      code: "SEMANTIC_INVALID",
      message: "Some of the details aren't valid.",
      details: { errors },
    };
  }

  return { code: "UNKNOWN", message: `${res.status} ${res.statusText}` };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new PlanError({
      code: "NETWORK",
      message: "Can't reach the NavigIQ server.",
    });
  }

  if (res.status === 401 && token) {
    setToken(null);
    onUnauthorized?.();
  }

  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error body */
    }
    throw new PlanError(toApiError(res, body));
  }
  if (res.status === 204) return undefined as T;   // No Content
  return res.json() as Promise<T>;
}

export function getCategories(): Promise<{ categories: Category[] }> {
  return request("/pois/categories");
}

/** Place name -> coordinates. Act on `confidence`: low means ask the user. */
export function resolvePlace(q: string): Promise<ResolveResult> {
  return request(`/places/resolve?q=${encodeURIComponent(q)}&limit=5`);
}

/** Plan one day. Takes a few seconds - show progress, not a bare spinner. */
export function createPlan(spec: TripSpec): Promise<PlanResponse> {
  return request("/plan", { method: "POST", body: JSON.stringify(spec) });
}

/** Places near a point. Categories match through links (a lake can be a sunset spot). */
export function searchPois(p: {
  lat: number; lon: number; radiusKm?: number; categories?: string[]; limit?: number;
}): Promise<{ count: number; results: PoiSummary[] }> {
  const q = new URLSearchParams({
    lat: String(p.lat),
    lon: String(p.lon),
    radius_km: String(p.radiusKm ?? 3),
    limit: String(p.limit ?? 12),
  });
  for (const c of p.categories ?? []) q.append("category", c);
  return request(`/pois/search?${q.toString()}`);
}

export function getPoi(id: number): Promise<PoiDetail> {
  return request(`/pois/${id}`);
}

// ------------------------------------------------------------------ accounts

/** Public sign-up: email and password only - the server decides the rest. */
export function register(email: string, password: string): Promise<UserMe> {
  return request("/auth/users", { method: "POST", body: JSON.stringify({ email, password }) });
}

/** OAuth2 password login. The backend expects FORM fields, not JSON. */
export async function login(email: string, password: string): Promise<void> {
  const body = new URLSearchParams({ username: email, password });
  const r = await request<{ access_token: string; token_type: string }>(
    "/auth/login/access-token", { method: "POST", body },
  );
  setToken(r.access_token);
}

export function getMe(): Promise<UserMe> {
  return request("/auth/users/me");
}

export function updateMe(patch: ProfilePatch): Promise<UserMe> {
  return request("/auth/users/me", { method: "PATCH", body: JSON.stringify(patch) });
}

/** Permanently delete the signed-in account. The password is asked again. */
export function deleteMe(password: string): Promise<void> {
  return request("/auth/users/me", { method: "DELETE", body: JSON.stringify({ password }) });
}

// -------------------------------------------------------------- saved plans

/** The signed-in user's plans, newest first. */
export function listItineraries(limit = 20): Promise<{ count: number; itineraries: SavedPlanSummary[] }> {
  return request(`/itineraries?limit=${limit}`);
}

export function getItinerary(id: number): Promise<SavedPlan> {
  return request(`/itineraries/${id}`);
}

export function deleteItinerary(id: number): Promise<void> {
  return request(`/itineraries/${id}`, { method: "DELETE" });
}