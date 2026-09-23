import { useSyncExternalStore } from "react";
import type { PlanResponse, TripSpec } from "../types";

/**
 * Plans the user made, kept in this browser. Real data - these are actual
 * planner results - but stored locally until GET /itineraries exists.
 */
export interface SavedPlan {
  id: string;
  savedAt: string;
  spec: TripSpec;
  data: PlanResponse;
}

const KEY = "navigiq.plans";
const MAX_PLANS = 20;
const listeners = new Set<() => void>();

function load(): SavedPlan[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as SavedPlan[]) : [];
  } catch {
    return [];
  }
}

let plans: SavedPlan[] = load();

function set(next: SavedPlan[]): void {
  plans = next;
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* storage full */ }
  listeners.forEach((l) => l());
}

export function useSavedPlans(): SavedPlan[] {
  return useSyncExternalStore(
    (l) => { listeners.add(l); return () => listeners.delete(l); },
    () => plans,
  );
}

export function savePlan(spec: TripSpec, data: PlanResponse): SavedPlan {
  const plan: SavedPlan = {
    id: String(data.itinerary.itinerary_id ?? Date.now()),
    savedAt: new Date().toISOString(),
    spec,
    data,
  };
  set([plan, ...plans.filter((p) => p.id !== plan.id)].slice(0, MAX_PLANS));
  return plan;
}

export function getPlan(id: string): SavedPlan | undefined {
  return plans.find((p) => p.id === id);
}

/** Forget every plan saved in this browser. */
export function clearPlans(): void {
  set([]);
}

export function deletePlan(id: string): void {
  set(plans.filter((p) => p.id !== id));
}
