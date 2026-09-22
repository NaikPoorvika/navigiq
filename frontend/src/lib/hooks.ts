import { useEffect, useRef, useState, useSyncExternalStore } from "react";

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const mql = window.matchMedia(query);
      mql.addEventListener("change", cb);
      return () => mql.removeEventListener("change", cb);
    },
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false),
    () => false,
  );
}

export const useIsDesktop = () => useMediaQuery("(min-width: 1024px)");
export const useReducedMotion = () => useMediaQuery("(prefers-reduced-motion: reduce)");

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Cycles through items (e.g. example prompts) unless reduced motion is on. */
export function useRotating<T>(items: readonly T[], ms = 3500): T | undefined {
  const reduced = useReducedMotion();
  const [i, setI] = useState(0);
  useEffect(() => {
    if (reduced || items.length < 2) return;
    const t = setInterval(() => setI((n) => (n + 1) % items.length), ms);
    return () => clearInterval(t);
  }, [items.length, ms, reduced]);
  return items[i % Math.max(1, items.length)];
}

/** Elapsed seconds while `active`, for honest progress copy on slow work. */
export function useElapsed(active: boolean): number {
  const [s, setS] = useState(0);
  const started = useRef<number | null>(null);
  useEffect(() => {
    if (!active) {
      started.current = null;
      setS(0);
      return;
    }
    started.current = Date.now();
    const t = setInterval(() => setS(Math.floor((Date.now() - (started.current ?? Date.now())) / 1000)), 500);
    return () => clearInterval(t);
  }, [active]);
  return s;
}

export function useDocumentTitle(title: string | undefined): void {
  useEffect(() => {
    if (title) document.title = `${title} · NavigIQ`;
  }, [title]);
}
