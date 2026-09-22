import type {
  ApiError, Category, FieldIssue, PlanResponse, PoiDetail, PoiSummary,
  ResolveResult, TripSpec,
} from "../types";

// Relative: Vite proxies /api to the backend (see vite.config.ts).
const BASE = "/api/v1";

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new PlanError({
      code: "NETWORK",
      message: "Can't reach the NavigIQ server.",
    });
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
