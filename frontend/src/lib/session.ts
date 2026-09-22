/**
 * Anonymous browser session. The backend accepts 16-64 characters of
 * [A-Za-z0-9_-] in X-NavigIQ-Session and uses it to own plans and
 * conversations until the person signs in (then the plans are claimed).
 */
const KEY = "navigiq.session";

function randomId(): string {
  const bytes = new Uint8Array(18);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

let cached: string | null = null;

export function getSessionId(): string {
  if (cached) return cached;
  try {
    const existing = window.localStorage.getItem(KEY);
    if (existing && /^[A-Za-z0-9_-]{16,64}$/.test(existing)) {
      cached = existing;
      return existing;
    }
    cached = randomId();
    window.localStorage.setItem(KEY, cached);
  } catch {
    cached ??= randomId();
  }
  return cached;
}
