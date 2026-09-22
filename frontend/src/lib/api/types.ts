/**
 * Types for the NavigIQ API (backend/app/api/v1). They describe what the
 * server sends; the UI never adds facts of its own to these objects.
 */

export interface CostRange {
  min: number;
  typical: number;
  max: number;
  confidence?: string;
  currency?: string;
  per?: string;
  basis?: "estimate";
  party_size?: number;
}

export interface DurationRange {
  min: number;
  typical: number;
  max: number;
}

export interface ImageAttribution {
  file?: string;
  artist?: string;
  license?: string;
  source_url?: string;
}

export type RegionBucket = "CITY_CORE" | "INNER_CITY" | "OUTER_CITY" | "OUTSKIRTS" | "REGIONAL" | string;

export interface PoiCard {
  id: number;
  slug: string;
  name: string;
  category: string;
  secondary_categories: string[];
  lat: number;
  lon: number;
  locality: string | null;
  neighborhood: string | null;
  district: string | null;
  region_bucket: RegionBucket;
  distance_from_center_km: number;
  short_description: string | null;
  experience_tags: string[];
  mood_tags: string[];
  indoor_outdoor: "indoor" | "outdoor" | "mixed";
  visit_duration: DurationRange;
  estimated_cost: CostRange;
  hours_confidence: number;
  image_url: string | null;
  image_attribution: ImageAttribution | null;
  is_chain: boolean;
  curated: boolean;
  short_escape: boolean;
  day_trip_suitable: boolean;
  recommended_as_primary_destination: boolean;
  source_names: string[];
}

/** A place ranked by the recommendation engine; `why` is derived from reason codes. */
export interface ScoredPoi extends PoiCard {
  score: number;
  reason_codes: string[];
  why: string[];
}

export interface OpeningHoursRow {
  day_of_week: number;
  open: string | null;
  close: string | null;
  is_24h: boolean;
  source: string;
  confidence: number;
  verified: boolean;
}

export interface SourceAttribution {
  name: string;
  license: string | null;
  url: string | null;
}

export interface PoiDetail extends PoiCard {
  description: string | null;
  description_source: string | null;
  address: string | null;
  wikidata_id?: string | null;
  wikipedia_title?: string | null;
  activity_tags: string[];
  food_tags: string[];
  dietary_tags: string[];
  accessibility_tags: string[];
  suitability: Record<string, boolean | null>;
  source_urls: string[];
  opening_hours: OpeningHoursRow[];
  hours_verified: boolean;
  attribution: SourceAttribution[];
  saved: boolean;
}

export interface RecommendMeta {
  scope: string;
  anchor: { name: string; lat: number; lon: number } | null;
  candidate_count: number;
  widened: boolean;
  notes: string[];
}

export interface RecommendResponse {
  items: ScoredPoi[];
  meta: RecommendMeta;
  attribution: string;
}

export interface PoiListResponse {
  count: number;
  items: PoiCard[];
  area: { name: string; lat: number; lon: number } | null;
  attribution: string;
}

export interface Collection {
  id: string;
  title: string;
  subtitle: string | null;
  items: ScoredPoi[];
}

export interface CollectionsResponse {
  collections: Collection[];
  available: { id: string; title: string; subtitle: string | null }[];
  attribution: string;
}

export interface CategoryInfo {
  key: string;
  name: string;
  group: string;
  theme: boolean;
  indoor_outdoor: string;
  typical_visit_minutes: number;
}

export interface WeatherWindow {
  available: boolean;
  heavy_rain_expected: boolean;
  rain_likely: boolean;
  max_precip_mm: number;
  max_precip_probability: number | null;
  mean_temp_c: number | null;
  condition: "dry" | "light_rain" | "rain_likely" | "heavy_rain" | "unknown" | string;
  degraded_reason: string | null;
  source: string;
}

export interface HomeContext {
  now: string;
  date: string;
  weekday: string;
  is_weekend: boolean;
  time_of_day: "morning" | "afternoon" | "evening" | "night";
  city: string;
  timezone: string;
  weather: WeatherWindow;
}

// --- plans ---------------------------------------------------------------------------------

export interface ItineraryStop {
  seq: number;
  day?: number;
  day_seq?: number;
  poi: PoiCard;
  arrive: string;
  depart: string;
  arrive_min: number;
  depart_min: number;
  visit_minutes: number;
  estimated_cost: CostRange;
  transition_buffer_before_min: number;
  free_time_before_min: number;
  hours_verified: boolean;
  reason_codes: string[];
  why: string[];
}

export interface PlanSummary {
  stop_count: number;
  day_count?: number;
  estimated_cost: CostRange & { excludes?: string };
  budget: number | null;
  within_budget: boolean;
  max_may_exceed_budget: boolean;
  total_visit_minutes: number;
  span_minutes: number;
  interests: string[];
  pace: string;
  party_size: number;
  party_type: string | null;
}

export interface MapFrame {
  center: { lat: number; lon: number } | null;
  bbox: [number, number, number, number] | null;
}

export interface TripSpec {
  version: string;
  date: string | null;
  end_date?: string | null;
  start_time: string | null;
  end_time: string | null;
  interests: string[];
  avoid_interests: string[];
  budget_total: number | null;
  budget_per_person: number | null;
  party_size: number | null;
  party_type: string | null;
  pace: "quick" | "balanced" | "relaxed";
  desired_stop_count: number | null;
  max_stop_count: number | null;
  anchor_area: { name: string; lat: number | null; lon: number | null } | null;
  must_include_poi_ids: number[];
  exclude_poi_ids: number[];
  indoor_preference: "indoor" | "outdoor" | "any" | null;
  meal_preferences: string[];
  dietary_preferences: string[];
  [key: string]: unknown;
}

export interface TripDay {
  day: number;
  date: string;
  title: string;
  localities: string[];
  categories: string[];
  start_time: string;
  end_time: string;
  summary: PlanSummary;
  weather: WeatherWindow | null;
  map: MapFrame;
  notes: string[];
  assumptions: string[];
  spec: TripSpec;
}

export interface Itinerary {
  kind?: "trip";
  title: string;
  date: string;
  end_date?: string;
  day_count?: number;
  start_time: string;
  end_time: string;
  days?: TripDay[];
  stops: ItineraryStop[];
  summary: PlanSummary;
  transition_buffer_minutes: number;
  transition_note: string;
  weather: (WeatherWindow & { days?: (WeatherWindow & { day: number })[] }) | null;
  map: MapFrame;
  assumptions: string[];
  notes: string[];
  attribution: string;
  itinerary_id?: number;
  version_no?: number;
  variant_id?: number;
}

export interface ValidatorReport {
  valid: boolean;
  rules_run: string[];
  findings: { rule: string; stop_seq: number | null; message: string; day?: number }[];
  recomputed_cost_inr: number;
}

export interface PlanOutcome {
  ok?: boolean;
  status: string;
  itinerary: Itinerary | null;
  trip_spec: TripSpec;
  assumptions: string[];
  warnings: string[];
  notes: string[];
  validator_report: ValidatorReport | null;
  weather: WeatherWindow | null;
  feasibility?: Feasibility | null;
}

export interface Relaxation {
  code: string;
  description: string;
  operation: Modification;
}

export interface Feasibility {
  feasible: boolean;
  message?: string;
  day?: number;
  suggested_relaxations?: Relaxation[];
}

export interface PlanView {
  itinerary_id: number;
  version_no: number;
  kind: string;
  label: string | null;
  reason: string;
  is_current: boolean;
  title: string;
  status: "draft" | "saved" | "abandoned";
  created_at: string | null;
  trip_spec: TripSpec;
  itinerary: Itinerary;
  validator_report: ValidatorReport;
}

export interface PlanListItem {
  itinerary_id: number;
  title: string;
  status: string;
  created_at: string | null;
  version_no: number;
  date: string | null;
  end_date: string | null;
  day_count: number;
  stop_count: number;
  stops_preview: string[];
  estimated_cost: CostRange | null;
}

export interface PlanVersion {
  itinerary_id: number;
  version_no: number | null;
  kind: "version" | "variant";
  variant_id: number | null;
  variant_status: "pending" | "applied" | "rejected" | null;
  reason: string;
  label: string | null;
  created_at: string | null;
  is_current: boolean;
  stop_count: number;
  estimated_cost_typical: number;
}

export type ModOp =
  | "remove_stop" | "add_poi" | "replace_stop" | "set_budget" | "set_start_time" | "set_end_time"
  | "shift_time" | "set_stop_count" | "set_pace" | "set_area" | "avoid_area" | "avoid_category"
  | "prefer_category" | "add_interest" | "remove_interest" | "set_indoor_preference"
  | "set_transition_buffer" | "add_meal";

export interface Modification {
  op: ModOp;
  target_seq?: number;
  poi_id?: number;
  amount?: number;
  time?: string | null;
  minutes?: number;
  count?: number;
  pace?: "quick" | "balanced" | "relaxed";
  area?: string | null;
  category?: string;
  interest?: string;
  preference?: "indoor" | "outdoor" | "any";
  meal?: "breakfast" | "lunch" | "dinner" | "snacks" | "coffee";
  day?: number;
}

export interface DayDiff {
  day: number;
  added: string[];
  removed: string[];
  retimed: string[];
  changed: boolean;
  estimated_cost: { current: number; variant: number; delta: number };
}

export interface Comparison {
  added: string[];
  removed: string[];
  retimed: string[];
  kept: string[];
  stop_count: { current: number; variant: number };
  estimated_cost: { current: number; variant: number; delta: number };
  window: { current: [string, string]; variant: [string, string] };
  span_minutes: { current: number; variant: number };
  days: DayDiff[] | null;
  changed_days: number[] | null;
}

export interface ModifyResponse extends PlanOutcome {
  summary: string[];
  version_no: number | null;
  variant_id: number | null;
  comparison: Comparison | null;
  previous_itinerary: Itinerary;
}

// --- assistant --------------------------------------------------------------------------------

export type AssistantUiType =
  | "message" | "discovery" | "poi_list" | "poi_details" | "comparison" | "knowledge_answer"
  | "clarification" | "trip_spec" | "itinerary" | "itinerary_comparison" | "feasibility_error"
  | "error";

export interface Citation {
  n: number;
  title: string;
  url: string | null;
  license?: string | null;
  source?: string;
  section?: string | null;
  excerpt?: string;
}

export interface Suggestion {
  label: string;
  message: string;
}

export interface AssistantResponse {
  conversation_id: string;
  intent: string;
  text: string;
  data: Record<string, unknown>;
  ui: { type: AssistantUiType; [key: string]: unknown };
  sources: Citation[];
  warnings: string[];
  suggestions: Suggestion[];
  trace_id: string;
  llm_used: boolean;
  llm_available: boolean;
}

// --- auth & me ----------------------------------------------------------------------------------

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface Preferences {
  /** Read-only: derived from what you do, returned by GET but not settable. */
  party_preferences?: string[];
  favorite_categories: string[];
  disliked_categories: string[];
  favorite_moods: string[];
  preferred_pace: "quick" | "balanced" | "relaxed" | null;
  typical_budget_inr: number | null;
  indoor_outdoor_preference: "indoor" | "outdoor" | "any" | null;
  dietary_preferences: string[];
  favorite_areas: string[];
}

export interface SavedItem extends PoiCard {
  saved_at?: string;
}
