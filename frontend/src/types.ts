// Mirrors the NavigIQ backend API.
// Times are MINUTES SINCE MIDNIGHT (902 = 15:02). Costs are integer rupees and
// always estimates: category figures are "typical", never a venue's real price.

export type Priority = "must" | "should" | "nice_to_have";
export type TransportMode = "walking" | "auto" | "cab" | "own_car" | "bike";
export type PlanningMode = "balanced" | "quick" | "relaxed";

export interface Category {
  key: string;
  display_name: string;
  default_visit_minutes: number;
  is_indoor: boolean;
  typical_cost_inr: number;
  meal_category: boolean;
  poi_count: number;
}

export interface Interest {
  category: string;
  count: number;
  priority: Priority;
}

export interface Place {
  name?: string;
  lat: number;
  lon: number;
}

export interface TripSpec {
  origin: Place;
  date: string;              // YYYY-MM-DD
  start_time_local: string;  // HH:MM
  end_time_local: string;
  budget_inr?: number | null;
  party_size: number;
  interests: Interest[];
  transport: TransportMode[];
  constraints: {
    max_walking_km: number;
    meal_required?: boolean;
    vegetarian?: boolean;
  };
  mode: PlanningMode;
  days?: number;
}

/** Real photo of a specific place, from Wikimedia Commons. Credit is required. */
export interface PhotoFields {
  image_url?: string | null;
  image_credit?: string | null;
  image_license?: string | null;
  image_source_url?: string | null;
}

export interface Stop extends PhotoFields {
  seq: number;
  poi_id: number;
  name: string;
  category: string;
  arrive_min: number;
  depart_min: number;
  visit_minutes: number;
  cost_inr: number;
  cost_basis: "poi_specific" | "category_estimate";
  mode_from_prev: string | null;
  travel_minutes_from_prev: number;
  lat: number;
  lon: number;
  /** False when the stop's opening hours are a category guess, not real data. */
  hours_verified?: boolean;
  /** The road shape from the previous stop, as an encoded polyline. */
  geometry?: string | null;
}

export interface Itinerary {
  status: string;
  total_cost_inr: number;
  total_duration_min: number;
  total_walk_m: number;
  cost_note?: string;
  estimated_cost_stops?: number;
  unsatisfied_must: string[];
  solve_ms: number;
  stops: Stop[];
  origin: Place;
  itinerary_id?: number;
}

export interface Weather {
  available: boolean;
  heavy_rain_expected: boolean;
  max_precip_mm: number;
  mean_temp_c: number | null;
  condition: string;
  degraded_reason?: string | null;
}

export interface PlanResponse {
  ok: boolean;
  itinerary: Itinerary;
  weather: Weather;
  relaxations_applied: string[];
  semantic_warnings: FieldIssue[];
  timings_ms: Record<string, number>;
  attribution: string;
}

export interface Relaxation {
  step: number;
  description: string;
  impact: string;
  requires_confirmation: boolean;
  action: string;
}

export interface FieldIssue {
  code?: string;
  field: string;
  message: string;
}

export type ErrorCode =
  | "INFEASIBLE"
  | "SEMANTIC_INVALID"
  | "NO_CANDIDATES"
  | "ROUTING_UNAVAILABLE"
  | "VALIDATION_FAILED"
  | "NETWORK"
  | "AUTH"
  | "UNKNOWN";

export interface ApiErrorDetails {
  violated?: string[];
  bounds?: Record<string, unknown>;
  suggested_relaxations?: Relaxation[];
  errors?: FieldIssue[];
  reason?: string;
}

/** Switch on `code`, never on `message`. */
export interface ApiError {
  code: ErrorCode;
  message: string;
  details?: ApiErrorDetails | null;
}

export interface PoiSummary extends PhotoFields {
  id: number;
  name: string;
  category: string;
  matched_category: string;
  lat: number;
  lon: number;
  distance_m: number;
  cost_estimate_inr: number | null;
  category_typical_inr: number;
  visit_minutes: number;
  indoor: boolean | null;
  hours_confidence: number | null;
  hours_verified: boolean;
  curated: boolean;
}

export interface OpeningHours {
  day_of_week: number;       // 0 = Monday
  open_min: number;
  close_min: number;
  is_24h: boolean;
  source: string;
  confidence: number;
  verified: boolean;
}

export interface PoiDetail extends PhotoFields {
  id: number;
  name: string;
  description: string | null;
  category: string;
  secondary_categories: { category: string; weight: number }[];
  lat: number;
  lon: number;
  cost_estimate_inr: number | null;
  category_typical_inr: number;
  cost_basis: string;
  visit_minutes: number;
  indoor: boolean | null;
  curated: boolean;
  source: string;
  source_ref: string;
  wikidata_id: string | null;
  opening_hours: OpeningHours[];
}

export interface PlaceMatch {
  name: string;
  lat: number;
  lon: number;
  kind: string;
  source: "place" | "poi";
}

export interface ResolveResult {
  query: string;
  match: PlaceMatch | null;
  alternatives: PlaceMatch[];
  confidence: "high" | "medium" | "low" | "none";
  needs_clarification: boolean;
}

/** GET /auth/users/me - the signed-in user and their planning profile. */
export interface UserMe {
  id: string;
  email: string;
  display_name: string | null;
  home_name: string | null;
  home_lat: number | null;
  home_lon: number | null;
  interests: string[];
  vegetarian: boolean;
}

/** PATCH /auth/users/me - only the fields sent are changed. */
export interface ProfilePatch {
  display_name?: string | null;
  home?: { name: string; lat: number; lon: number } | null;
  interests?: string[];
  vegetarian?: boolean;
}

/** 902 -> "15:02" */
export function hhmm(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** 1234 -> "1.2 km", 640 -> "640 m" */
export function distanceLabel(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}

/** 167 -> "2 h 47 min" */
export function durationLabel(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

/** Category estimates are shown as typical, never as the venue's price. */
export function costLabel(stop: Stop): string {
  if (stop.cost_inr === 0) return "Free";
  return stop.cost_basis === "category_estimate"
    ? `≈ ₹${stop.cost_inr} typical`
    : `₹${stop.cost_inr}`;
}
