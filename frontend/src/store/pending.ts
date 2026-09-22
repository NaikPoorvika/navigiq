import type { TripSpec } from "../types";

/** Hands a prepared request from one page to the planner page. */
let pending: { spec: Partial<TripSpec>; autoPlan: boolean } | null = null;

export function setPendingPlan(spec: Partial<TripSpec>, autoPlan = false): void {
  pending = { spec, autoPlan };
}

export function takePendingPlan(): { spec: Partial<TripSpec>; autoPlan: boolean } | null {
  const p = pending;
  pending = null;
  return p;
}
