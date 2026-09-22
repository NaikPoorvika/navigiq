import { useSyncExternalStore } from "react";
import type { Place } from "../types";

/**
 * PREVIEW ACCOUNT STORE. Accounts live in this browser's localStorage until
 * the real /auth endpoints are connected. Nothing here is a security check -
 * this is the single seam to replace with the backend.
 */
export interface Profile {
  name: string;
  email: string;
  home: Place | null;
  interests: string[];
  vegetarian: boolean;
}

export interface AccountState {
  profile: Profile | null;
  signedIn: boolean;
}

const PROFILE_KEY = "navigiq.profile";
const SESSION_KEY = "navigiq.session";
const listeners = new Set<() => void>();

function load(): AccountState {
  try {
    const raw = localStorage.getItem(PROFILE_KEY);
    const profile = raw ? (JSON.parse(raw) as Profile) : null;
    return { profile, signedIn: profile !== null && localStorage.getItem(SESSION_KEY) === "1" };
  } catch {
    return { profile: null, signedIn: false };
  }
}

let state: AccountState = load();

function set(next: AccountState): void {
  state = next;
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useAccount(): AccountState {
  return useSyncExternalStore(subscribe, () => state);
}

export function saveProfile(profile: Profile): void {
  try {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
    localStorage.setItem(SESSION_KEY, "1");
  } catch {
    /* storage unavailable - keep in memory */
  }
  set({ profile, signedIn: true });
}

/** Preview sign-in: succeeds only for the account created in this browser. */
export function signIn(email: string): boolean {
  const current = state.profile;
  if (!current || current.email.toLowerCase() !== email.trim().toLowerCase()) return false;
  try { localStorage.setItem(SESSION_KEY, "1"); } catch { /* ignore */ }
  set({ profile: current, signedIn: true });
  return true;
}

export function signOut(): void {
  try { localStorage.removeItem(SESSION_KEY); } catch { /* ignore */ }
  set({ profile: state.profile, signedIn: false });
}

export function deleteAccount(): void {
  try {
    localStorage.removeItem(PROFILE_KEY);
    localStorage.removeItem(SESSION_KEY);
  } catch { /* ignore */ }
  set({ profile: null, signedIn: false });
}
