/** Recent Ask prompts, kept on this device only. */
const KEY = "navigiq.recentPrompts";
const MAX = 5;

export function recentPrompts(): string[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    const list = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(list) ? list.filter((x): x is string => typeof x === "string").slice(0, MAX) : [];
  } catch {
    return [];
  }
}

export function rememberPrompt(text: string): void {
  const t = text.trim();
  if (t.length < 3) return;
  try {
    const next = [t, ...recentPrompts().filter((p) => p.toLowerCase() !== t.toLowerCase())].slice(0, MAX);
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // storage unavailable: nothing to remember
  }
}

export function clearPrompts(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
