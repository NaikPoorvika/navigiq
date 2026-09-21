// Mirrors the backend TripSpec (NQ-021) and plan response (NQ-025).
// Times are MINUTES SINCE MIDNIGHT: arrive_min 902 = 15:02.
// Costs are integer rupees. Everything is basis: "estimate".

export type Priority = "must" | "should" | "nice_to_have";

export type TransportMode =
  | "walking" | "auto" | "cab" | "own_car" | "bike";

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

export interface TripSpec {
  origin: { lat: number; lon: number; name?: string };
  date: string;              // YYYY-MM-DD
  start_time_local: string;  // HH:MM
  end_time_local: string;
  budget_inr?: number | null;
  party_size: number;
  interests: Interest[];
  transport: TransportMode[];
  constraints: {
    max_walking_km: number;
    meal_required: boolean;
    vegetarian?: boolean;
  };
  mode: "balanced" | "quick" | "relaxed";
}

export interface Stop {
  seq: number;
  poi_id: number;
  name: string;
  category: string;
  arrive_min: number;
  depart_min: number;
  visit_minutes: number;
  cost_inr: number;
  mode_from_prev: string | null;
  travel_minutes_from_prev: number;
  // Filled in by the client from /pois/{id} - the plan response does not
  // include coordinates. See the note to A1.
  lat?: number;
  lon?: number;
}

export interface Itinerary {
  status: string;
  optimizer: string;
  total_cost_inr: number;
  total_duration_min: number;
  total_walk_m: number;
  objective_value: number;
  solve_ms: number;
  unsatisfied_must: string[];
  stops: Stop[];
  itinerary_id?: number;
}

export interface Weather {
  available: boolean;
  heavy_rain_expected: boolean;
  max_precip_mm: number;
  mean_temp_c: number | null;
  condition: string;
  source: string;
}

export interface PlanResponse {
  ok: boolean;
  itinerary: Itinerary;
  weather: Weather;
  validator_report: { valid: boolean; rules_run: string[]; findings: unknown[] };
  relaxations_applied: string[];
  semantic_warnings: { code: string; field: string; message: string }[];
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

/** The backend returns a stable `code`. Switch on that, never on message. */
export interface ApiError {
  code: string;
  message: string;
  details?: {
    violated?: string[];
    bounds?: Record<string, number>;
    suggested_relaxations?: Relaxation[];
    errors?: { code: string; field: string; message: string }[];
  };
}

/** 902 -> "15:02" */
export function hhmm(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}