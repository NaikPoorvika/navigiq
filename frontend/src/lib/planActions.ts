/**
 * Quick changes, expressed as the backend's closed modification operations.
 * The numbers they carry come from the plan itself (e.g. "cheaper" targets
 * 75% of the current estimate, as the conversational parser does).
 */
import type { Itinerary, Modification, TripSpec } from "@/lib/api/types";
import { daysOf, isTrip } from "@/lib/plan";

export interface QuickAction {
  id: string;
  label: string;
  /** Describes the effect, for the "Updating…" status and the undo toast. */
  doing: string;
  ops: Modification[];
  disabled?: string | false;
}

function specFor(it: Itinerary, spec: TripSpec, day?: number): TripSpec {
  if (day && isTrip(it)) return it.days?.find((d) => d.day === day)?.spec ?? spec;
  return spec;
}

export function quickActions(it: Itinerary, spec: TripSpec, day?: number): QuickAction[] {
  const trip = isTrip(it);
  const scoped = trip && day ? { day } : {};
  const dv = daysOf(it).find((d) => d.day === (day ?? 1));
  const s = specFor(it, spec, day);
  const cost = day && trip ? dv?.meta?.summary.estimated_cost.typical ?? 0 : it.summary.estimated_cost.typical;
  const stopCount = day && trip ? dv?.stops.length ?? 0 : trip ? Math.max(...daysOf(it).map((d) => d.stops.length)) : it.stops.length;
  const cheaper = Math.floor((cost * 0.75) / 50) * 50;
  const where = trip && day ? `day ${day}` : trip ? "every day" : "the plan";
  return [
    {
      id: "cheaper", label: "Make it cheaper", doing: `Finding a cheaper version of ${where}`,
      ops: [{ op: "set_budget", amount: cheaper, ...scoped }],
      disabled: cost <= 0 ? "Already free" : false,
    },
    {
      id: "relaxed", label: "More relaxed", doing: `Slowing down ${where}`,
      ops: [{ op: "set_pace", pace: "relaxed", ...scoped }],
      disabled: s.pace === "relaxed" ? "Already relaxed" : false,
    },
    {
      id: "romantic", label: "More romantic", doing: `Making ${where} more romantic`,
      ops: [{ op: "add_interest", interest: "romantic", ...scoped }],
      disabled: s.interests.includes("romantic") ? "Already romantic" : false,
    },
    {
      id: "indoor", label: "Keep it indoors", doing: `Moving ${where} indoors`,
      ops: [{ op: "set_indoor_preference", preference: "indoor", ...scoped }],
      disabled: s.indoor_preference === "indoor" ? "Already indoors" : false,
    },
    {
      id: "fewer", label: "Fewer stops", doing: `Trimming ${where}`,
      ops: [{ op: "set_stop_count", count: Math.max(1, stopCount - 1), ...scoped }],
      disabled: stopCount <= 1 ? "Only one stop" : false,
    },
    {
      id: "packed", label: "Pack in more", doing: `Fitting more into ${where}`,
      ops: [{ op: "set_pace", pace: "quick", ...scoped }],
      disabled: s.pace === "quick" ? "Already quick" : false,
    },
    {
      id: "later", label: "Start an hour later", doing: `Shifting ${where} an hour later`,
      ops: [{ op: "shift_time", minutes: 60, ...scoped }],
    },
    {
      id: "lunch", label: "Add lunch", doing: `Adding a lunch stop to ${where}`,
      ops: [{ op: "add_meal", meal: "lunch", ...scoped }],
      disabled: s.meal_preferences.includes("lunch") ? "Lunch is already planned" : false,
    },
    {
      id: "dinner", label: "Add dinner", doing: `Adding dinner to ${where}`,
      ops: [{ op: "add_meal", meal: "dinner", ...scoped }],
      disabled: s.meal_preferences.includes("dinner") ? "Dinner is already planned" : false,
    },
  ];
}

/** What a change keeps, in plain words, for the "Updating…" panel. */
export function keptConstraints(it: Itinerary, spec: TripSpec, day?: number): string[] {
  const s = specFor(it, spec, day);
  const out: string[] = [];
  if (s.start_time && s.end_time) out.push(`${s.start_time}–${s.end_time}`);
  const budget = s.budget_total ?? (s.budget_per_person !== null ? s.budget_per_person * (s.party_size ?? 1) : null);
  if (budget !== null && budget !== undefined) out.push(`budget ₹${budget}`);
  if (s.interests.length) out.push(s.interests.slice(0, 3).map((i) => i.replace(/_/g, " ")).join(", "));
  if (isTrip(it) && day) out.push("the other days as they are");
  return out;
}
