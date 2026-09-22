/**
 * Sign-in state. Anonymous use is first-class: discovery, the assistant and
 * planning all work without an account (the browser session owns plans).
 * An account adds saved places, preferences and plans across devices; on
 * sign-in the backend claims this browser's anonymous plans.
 */
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { refreshSession } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import { tokenStore } from "@/lib/api/tokens";
import type { User } from "@/lib/api/types";
import { getSessionId } from "@/lib/session";

interface AuthValue {
  user: User | null;
  /** False until a stored session has been restored (or found missing). */
  ready: boolean;
  isAuthenticated: boolean;
  signIn: (email: string, password: string) => Promise<User>;
  signUp: (email: string, password: string, displayName?: string) => Promise<User>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

function useStoredUser(): User | null {
  return useSyncExternalStore(
    (fn) => tokenStore.subscribe(fn),
    () => tokenStore.user,
    () => null,
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const user = useStoredUser();
  const qc = useQueryClient();
  const [ready, setReady] = useState(() => !tokenStore.refreshToken);

  useEffect(() => {
    if (!tokenStore.refreshToken || tokenStore.accessToken) {
      setReady(true);
      return;
    }
    // Restore the session. refreshSession() de-duplicates, so React's
    // double-invoked effects can't burn the one-use refresh token.
    let cancelled = false;
    void refreshSession().then((ok) => {
      if (cancelled) return;
      // Anything fetched while the session was still being restored was
      // fetched anonymously (e.g. an empty plan list); fetch it again.
      if (ok) void qc.invalidateQueries();
    }).finally(() => {
      if (!cancelled) setReady(true);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const afterAuthChange = useCallback(() => {
    void qc.invalidateQueries();
  }, [qc]);

  const signIn = useCallback(async (email: string, password: string) => {
    const pair = await endpoints.login(email, password, getSessionId());
    tokenStore.set(pair);
    afterAuthChange();
    return pair.user;
  }, [afterAuthChange]);

  const signUp = useCallback(async (email: string, password: string, displayName?: string) => {
    const pair = await endpoints.register(email, password, displayName);
    tokenStore.set(pair);
    afterAuthChange();
    return pair.user;
  }, [afterAuthChange]);

  const signOut = useCallback(async () => {
    const refresh = tokenStore.refreshToken;
    tokenStore.clear();
    if (refresh) {
      try {
        await endpoints.logout(refresh);
      } catch {
        // already signed out locally; the token will expire on its own
      }
    }
    afterAuthChange();
  }, [afterAuthChange]);

  const value = useMemo<AuthValue>(() => ({
    user, ready, isAuthenticated: Boolean(user), signIn, signUp, signOut,
  }), [user, ready, signIn, signUp, signOut]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
