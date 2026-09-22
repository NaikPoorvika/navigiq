/**
 * Token storage. The access token lives in memory only; the refresh token is
 * kept in localStorage so a reload can silently restore the session. The
 * backend rotates refresh tokens on every use and revokes them on logout.
 */
import type { TokenPair, User } from "@/lib/api/types";

const REFRESH_KEY = "navigiq.refresh";
const USER_KEY = "navigiq.user";

type Listener = () => void;

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // storage unavailable (private mode): the session lasts for this tab only
  }
}

class TokenStore {
  accessToken: string | null = null;
  refreshToken: string | null = readStorage(REFRESH_KEY);
  user: User | null = (() => {
    const raw = readStorage(USER_KEY);
    try {
      return raw ? (JSON.parse(raw) as User) : null;
    } catch {
      return null;
    }
  })();
  private listeners = new Set<Listener>();

  set(pair: TokenPair): void {
    this.accessToken = pair.access_token;
    this.refreshToken = pair.refresh_token;
    this.user = pair.user;
    writeStorage(REFRESH_KEY, pair.refresh_token);
    writeStorage(USER_KEY, JSON.stringify(pair.user));
    this.emit();
  }

  clear(): void {
    this.accessToken = null;
    this.refreshToken = null;
    this.user = null;
    writeStorage(REFRESH_KEY, null);
    writeStorage(USER_KEY, null);
    this.emit();
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(): void {
    this.listeners.forEach((fn) => fn());
  }
}

export const tokenStore = new TokenStore();
