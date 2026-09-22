/**
 * Fixtures for component tests. These are trimmed copies of real API
 * responses from the development database — never invented shapes.
 */
import type { Itinerary, PoiCard, ScoredPoi } from "@/lib/api/types";

export const lalbagh: ScoredPoi = {
  id: 10753,
  slug: "lalbagh-botanical-garden-way15802464",
  name: "Lalbagh Botanical Garden",
  category: "garden",
  secondary_categories: ["nature"],
  lat: 12.9488929,
  lon: 77.5866687,
  locality: "Shanti Nagar",
  neighborhood: "Siddapura",
  district: "Bengaluru Urban",
  region_bucket: "CITY_CORE",
  distance_from_center_km: 2.7,
  short_description: "A sprawling historic botanical garden with old trees, a glasshouse, a lake and an ancient rock outcrop.",
  experience_tags: ["nature", "peaceful", "photogenic"],
  mood_tags: ["nature", "peaceful"],
  indoor_outdoor: "outdoor",
  visit_duration: { min: 60, typical: 120, max: 180 },
  estimated_cost: { min: 0, typical: 30, max: 60, confidence: "curated_estimate", currency: "INR", per: "person", basis: "estimate" },
  hours_confidence: 0.3,
  image_url: null,
  image_attribution: null,
  is_chain: false,
  curated: true,
  short_escape: false,
  day_trip_suitable: false,
  recommended_as_primary_destination: false,
  source_names: ["OpenStreetMap", "Wikipedia"],
  score: 0.72,
  reason_codes: ["MATCHES_GARDEN", "GOOD_FOR_PHOTOGRAPHY"],
  why: ["Matches garden", "Photogenic"],
};

export const cubbon: PoiCard = {
  ...lalbagh,
  id: 10754,
  slug: "cubbon-park",
  name: "Cubbon Park",
  category: "park",
  locality: "Sampangi Rama Nagar",
  short_description: "The city's great central park — shaded avenues, lawns and colonial-era buildings.",
  estimated_cost: { min: 0, typical: 0, max: 0, currency: "INR", per: "person", basis: "estimate" },
};

function stop(seq: number, day: number, daySeq: number, poi: PoiCard, arrive: string, depart: string, cost: number) {
  return {
    seq, day, day_seq: daySeq, poi,
    arrive, depart,
    arrive_min: Number(arrive.slice(0, 2)) * 60 + Number(arrive.slice(3)),
    depart_min: Number(depart.slice(0, 2)) * 60 + Number(depart.slice(3)),
    visit_minutes: 90,
    estimated_cost: { min: cost, typical: cost, max: cost * 2, party_size: 2, confidence: "curated_estimate" },
    transition_buffer_before_min: seq === 1 ? 0 : 15,
    free_time_before_min: 0,
    hours_verified: false,
    reason_codes: ["MATCHES_GARDEN"],
    why: ["Matches garden"],
  };
}

const summary = (stops: number, typical: number, days?: number) => ({
  stop_count: stops,
  ...(days ? { day_count: days } : {}),
  estimated_cost: { min: typical, typical, max: typical * 2, currency: "INR", basis: "estimate" as const, excludes: "transportation" },
  budget: 4000,
  within_budget: true,
  max_may_exceed_budget: false,
  total_visit_minutes: stops * 90,
  span_minutes: 300,
  interests: ["garden", "museum"],
  pace: "balanced",
  party_size: 2,
  party_type: null,
});

export const singleDayPlan: Itinerary = {
  title: "Garden & Museum day",
  date: "2026-09-26",
  start_time: "10:00",
  end_time: "18:00",
  stops: [
    { ...stop(1, 1, 1, lalbagh, "10:00", "11:30", 60), day: undefined, day_seq: undefined },
    { ...stop(2, 1, 2, cubbon, "11:45", "13:15", 0), day: undefined, day_seq: undefined },
  ],
  summary: summary(2, 60),
  transition_buffer_minutes: 15,
  transition_note: "Transition buffers are included between stops. Actual transportation time is not calculated in this version.",
  weather: null,
  map: { center: null, bbox: null },
  assumptions: ["Time window 10:00–18:00"],
  notes: [],
  attribution: "Place data © OpenStreetMap contributors (ODbL)",
  itinerary_id: 42,
  version_no: 1,
};

export const tripPlan: Itinerary = {
  kind: "trip",
  title: "2-day Garden & Museum trip",
  date: "2026-09-26",
  end_date: "2026-09-27",
  day_count: 2,
  start_time: "10:00",
  end_time: "18:00",
  days: [
    {
      day: 1, date: "2026-09-26", title: "Shanti Nagar", localities: ["Shanti Nagar"], categories: ["Garden"],
      start_time: "10:00", end_time: "18:00", summary: summary(1, 60), weather: null,
      map: { center: null, bbox: null }, notes: [], assumptions: [],
      spec: { version: "2.0", date: "2026-09-26", start_time: "10:00", end_time: "18:00", interests: ["garden"], avoid_interests: [], budget_total: 2000, budget_per_person: null, party_size: 2, party_type: null, pace: "balanced", desired_stop_count: null, max_stop_count: null, anchor_area: null, must_include_poi_ids: [], exclude_poi_ids: [], indoor_preference: null, meal_preferences: [], dietary_preferences: [] },
    },
    {
      day: 2, date: "2026-09-27", title: "Sampangi Rama Nagar", localities: ["Sampangi Rama Nagar"], categories: ["Park"],
      start_time: "10:00", end_time: "18:00", summary: summary(1, 0), weather: null,
      map: { center: null, bbox: null }, notes: [], assumptions: [],
      spec: { version: "2.0", date: "2026-09-27", start_time: "10:00", end_time: "18:00", interests: ["garden"], avoid_interests: [], budget_total: 2000, budget_per_person: null, party_size: 2, party_type: null, pace: "relaxed", desired_stop_count: null, max_stop_count: null, anchor_area: null, must_include_poi_ids: [], exclude_poi_ids: [], indoor_preference: null, meal_preferences: [], dietary_preferences: [] },
    },
  ],
  stops: [stop(1, 1, 1, lalbagh, "10:00", "11:30", 60), stop(2, 2, 1, cubbon, "10:00", "11:30", 0)],
  summary: summary(2, 60, 2),
  transition_buffer_minutes: 15,
  transition_note: "Transition buffers are included between stops. Actual transportation time is not calculated in this version.",
  weather: { available: false, heavy_rain_expected: false, rain_likely: false, max_precip_mm: 0, max_precip_probability: null, mean_temp_c: null, condition: "unknown", degraded_reason: "weather disabled", source: "open-meteo" },
  map: { center: null, bbox: null },
  assumptions: ["2 days: Sat 26 Sep – Sun 27 Sep", "Budget split evenly: about ₹2000 per day"],
  notes: [],
  attribution: "Place data © OpenStreetMap contributors (ODbL)",
  itinerary_id: 43,
  version_no: 1,
};
