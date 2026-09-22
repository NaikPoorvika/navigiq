/** Helpers for single-day and multi-day itineraries (see backend trips.py). */
import type { Itinerary, ItineraryStop, TripDay } from "@/lib/api/types";

export function isTrip(it: Itinerary | null | undefined): boolean {
  return Boolean(it && it.kind === "trip" && it.days && it.days.length > 1);
}

export interface DayView {
  day: number;
  date: string;
  title: string | null;
  start_time: string;
  end_time: string;
  stops: ItineraryStop[];
  meta: TripDay | null;
}

/** Days with their stops; a single-day plan is one day. Stop `seq` stays trip-wide. */
export function daysOf(it: Itinerary): DayView[] {
  if (isTrip(it) && it.days) {
    return it.days.map((d) => ({
      day: d.day, date: d.date, title: d.title, start_time: d.start_time, end_time: d.end_time,
      stops: it.stops.filter((s) => s.day === d.day), meta: d,
    }));
  }
  return [{ day: 1, date: it.date, title: null, start_time: it.start_time, end_time: it.end_time, stops: it.stops, meta: null }];
}

/** The number to show on a stop within its day (trips number stops per day). */
export function localSeq(stop: ItineraryStop): number {
  return stop.day_seq ?? stop.seq;
}

export const PACE_LABEL: Record<string, string> = { quick: "Quick", balanced: "Balanced", relaxed: "Relaxed" };

/** Validator rules translated into what they mean for a person. */
export const CHECKS = [
  "Open at the time you'd arrive",
  "Within your budget (estimate)",
  "Stops don't overlap, with buffers between them",
  "Inside your time window",
];
