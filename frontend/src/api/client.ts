import type { ApiError, Category, PlanResponse, TripSpec } from "../types";

const BASE = "/api/v1";

/** Thrown for any non-2xx. Carries the backend's stable error code. */
export class PlanError extends Error {
  code: string;
  details?: ApiError["details"];

  constructor(err: ApiError) {
    super(err.message);
    this.code = err.code;
    this.details = err.details;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!res.ok) {
    let body: { detail?: { error?: ApiError } } = {};
    try {
      body = await res.json();
    } catch {
      throw new PlanError({
        code: "UNKNOWN",
        message: `${res.status} ${res.statusText}`,
      });
    }
    const err = body.detail?.error;
    throw new PlanError(
      err ?? { code: "UNKNOWN", message: `${res.status} ${res.statusText}` },
    );
  }

  return res.json() as Promise<T>;
}

export function getCategories(): Promise<{ categories: Category[] }> {
  return request("/pois/categories");
}

/**
 * Plan a trip. TAKES ABOUT 15 SECONDS - arc building dominates. Show staged
 * progress, not a spinner.
 *
 * Throws PlanError with a stable code:
 *   INFEASIBLE (409)          details.suggested_relaxations are actionable
 *   NO_CANDIDATES (404)       no POIs match a requested category
 *   ROUTING_UNAVAILABLE (503) OSRM down; no itinerary rather than a guess
 *   SEMANTIC_INVALID (422)    the request contradicts itself
 */
export function createPlan(spec: TripSpec): Promise<PlanResponse> {
  return request("/plan", { method: "POST", body: JSON.stringify(spec) });
}

export function getPoi(id: number): Promise<{ lat: number; lon: number }> {
  return request(`/pois/${id}`);
}

/**
 * The plan response carries poi_id but no coordinates, so each stop needs a
 * second call before it can be plotted.
 *
 * TODO(A1): add lat/lon to the stop payload - two lines server-side, saves
 * one round trip per stop.
 */
export async function attachCoordinates<T extends { poi_id: number }>(
  stops: T[],
): Promise<(T & { lat: number; lon: number })[]> {
  const details = await Promise.all(stops.map((s) => getPoi(s.poi_id)));
  return stops.map((s, i) => ({
    ...s,
    lat: details[i].lat,
    lon: details[i].lon,
  }));
}