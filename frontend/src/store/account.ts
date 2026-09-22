import { useSyncExternalStore } from "react";
import {
  getMe, getToken, login, register, setToken, setUnauthorizedHandler, updateMe,
} from "../api/client";
import type { Place, UserMe } from "../types";

/**
 * The signed-in user, backed by the real /auth API. The token is kept in the
 * browser; the profile lives on the server, so it follows the account.
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
  /** False until a saved token has been checked with the server. */
  ready: boolean;
}

const listeners = new Set<() => void>();
let state: AccountState = { profile: null, signedIn: false, ready: getToken() === null };

function set(next: AccountState): void {
  state = next;
  listeners.forEach((l) => l());
}

function toProfile(u: UserMe): Profile {
  return {
    name: u.display_name ?? u.email.split("@")[0] ?? u.email,
    email: u.email,
    home: u.home_lat != null && u.home_lon != null
      ? { name: u.home_name ?? "Home", lat: u.home_lat, lon: u.home_lon }
      : null,
    interests: u.interests,
    vegetarian: u.vegetarian,
  };
}

function signedInAs(me: UserMe): void {
  set({ profile: toProfile(me), signedIn: true, ready: true });
}

export function useAccount(): AccountState {
  return useSyncExternalStore(
    (l) => { listeners.add(l); return () => listeners.delete(l); },
    () => state,
  );
}

// An expired or rejected token signs the user out everywhere.
setUnauthorizedHandler(() => set({ profile: null, signedIn: false, ready: true }));

/** On load: if a token is saved, ask the server who it belongs to. */
async function restoreSession(): Promise<void> {
  if (!getToken()) return;
  try {
    signedInAs(await getMe());
  } catch {
    setToken(null);
    set({ profile: null, signedIn: false, ready: true });
  }
}
void restoreSession();

export async function signUp(email: string, password: string): Promise<void> {
  await register(email, password);
  await login(email, password);
  signedInAs(await getMe());
}

export async function signIn(email: string, password: string): Promise<void> {
  await login(email, password);
  signedInAs(await getMe());
}

export async function saveProfile(changes: {
  name?: string;
  home?: Place | null;
  interests?: string[];
  vegetarian?: boolean;
}): Promise<void> {
  const me = await updateMe({
    ...(changes.name !== undefined ? { display_name: changes.name } : {}),
    ...(changes.home !== undefined
      ? { home: changes.home ? { name: changes.home.name ?? "Home", lat: changes.home.lat, lon: changes.home.lon } : null }
      : {}),
    ...(changes.interests !== undefined ? { interests: changes.interests } : {}),
    ...(changes.vegetarian !== undefined ? { vegetarian: changes.vegetarian } : {}),
  });
  signedInAs(me);
}

export function signOut(): void {
  setToken(null);
  set({ profile: null, signedIn: false, ready: true });
}
