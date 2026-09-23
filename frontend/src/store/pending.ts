import type { TripSpec } from "../types";

/**
 * Hands a prepared request from one page to the planner page.
 *
 * Reading does NOT clear it. React mounts a page twice in development, and a
 * store that cleared on read gave the request to the first mount and an empty
 * form to the second - the one on screen. Each request carries a token
 * instead, and the planner plans a token once.
 */
export interface PendingPlan {
  spec: Partial<TripSpec>;
  autoPlan: boolean;
  token: string;
}

let pending: PendingPlan | null = null;
let counter = 0;

export function setPendingPlan(spec: Partial<TripSpec>, autoPlan = false): void {
  counter += 1;
  pending = { spec, autoPlan, token: `${Date.now()}-${counter}` };
}

/** The current request, if any. Safe to call on every render. */
export function peekPendingPlan(): PendingPlan | null {
  return pending;
}

export function clearPendingPlan(): void {
  pending = null;
}