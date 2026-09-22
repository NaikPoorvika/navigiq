/**
 * Formatting. Only presentation: every number comes from the API. Costs are
 * always labelled as estimates and say what they exclude.
 */
import type { CostRange, DurationRange } from "@/lib/api/types";

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function rupees(n: number): string {
  return `₹${inr.format(Math.round(n))}`;
}

/** "Free", "~₹200" or "₹150–₹400" from a cost range (per person unless stated). */
export function costLabel(c: CostRange | null | undefined): string {
  if (!c) return "Cost unknown";
  if (c.max === 0) return "Free";
  if (c.min === c.max) return `~${rupees(c.typical)}`;
  return `${rupees(c.min)}–${rupees(c.max)}`;
}

export function costShort(c: CostRange | null | undefined): string {
  if (!c) return "—";
  if (c.max === 0) return "Free";
  return `~${rupees(c.typical)}`;
}

export function minutesLabel(m: number): string {
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h} h ${r} min` : `${h} h`;
}

export function durationLabel(d: DurationRange | null | undefined): string {
  if (!d) return "";
  return minutesLabel(d.typical);
}

/** "14:30" -> "2:30 pm" (the API uses 24h local time, Asia/Kolkata). */
export function clock(hhmm: string | null | undefined): string {
  if (!hhmm) return "";
  const [hStr, mStr] = hhmm.split(":");
  const h = Number(hStr);
  const m = Number(mStr);
  if (Number.isNaN(h) || Number.isNaN(m)) return hhmm;
  const suffix = h >= 12 ? "pm" : "am";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m === 0 ? `${h12} ${suffix}` : `${h12}:${String(m).padStart(2, "0")} ${suffix}`;
}

export function clockRange(a: string, b: string): string {
  return `${clock(a)} – ${clock(b)}`;
}

const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WEEKDAY_LONG = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Parse "YYYY-MM-DD" as a calendar date (no timezone shifts). */
export function parseDate(iso: string): { y: number; m: number; d: number; weekday: number } {
  const [y, m, d] = iso.split("-").map(Number) as [number, number, number];
  const weekday = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return { y, m, d, weekday };
}

export function dateLabel(iso: string | null | undefined, long = false): string {
  if (!iso) return "";
  const { m, d, weekday } = parseDate(iso);
  return long ? `${WEEKDAY_LONG[weekday]}, ${d} ${MONTH[m - 1]}` : `${WEEKDAY[weekday]} ${d} ${MONTH[m - 1]}`;
}

export function dateRangeLabel(a: string, b?: string | null): string {
  if (!b || a === b) return dateLabel(a, true);
  return `${dateLabel(a)} – ${dateLabel(b)}`;
}

/** Today's date in Bengaluru, "YYYY-MM-DD", from the device clock. */
export function todayIST(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(now);
  return parts;
}

export function addDays(iso: string, n: number): string {
  const { y, m, d } = parseDate(iso);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return t.toISOString().slice(0, 10);
}

export function relativeDay(iso: string, today: string = todayIST()): string | null {
  if (iso === today) return "Today";
  if (iso === addDays(today, 1)) return "Tomorrow";
  return null;
}

export function distanceLabel(km: number): string {
  return km < 1 ? `${Math.round(km * 1000)} m from the centre` : `${km.toFixed(km < 10 ? 1 : 0)} km from the centre`;
}

export function regionLabel(bucket: string): string {
  switch (bucket) {
    case "CITY_CORE":
      return "Central Bengaluru";
    case "CITY":
      return "Bengaluru";
    case "OUTSKIRTS":
      return "Outskirts";
    case "NEARBY_ESCAPE":
      return "Day trip";
    default:
      return bucket.replace(/_/g, " ").toLowerCase();
  }
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function signedRupees(delta: number): string {
  if (delta === 0) return "same cost";
  return `${delta > 0 ? "+" : "−"}${rupees(Math.abs(delta))}`;
}
