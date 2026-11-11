// The merchant's API key lives in this browser only (localStorage). Without a key the console shows NOTHING: the visitor must connect a store, or choose the built-in demo shop on purpose.
const K = "landfall_api_key";
const D = "landfall_demo";

export function getKey(): string | null {
  try { return typeof window === "undefined" ? null : window.localStorage.getItem(K); } catch { return null; }
}

/** Tells the shell (shop name in the sidebar) that the signed-in merchant changed. */
export const KEY_EVENT = "landfall-key";

export function setKey(key: string): void {
  try { window.localStorage.setItem(K, key); } catch { /* private mode: the key then lives for this page only */ }
  window.dispatchEvent(new Event(KEY_EVENT));
}

export function clearKey(): void {
  try { window.localStorage.removeItem(K); } catch { /* nothing stored */ }
  window.dispatchEvent(new Event(KEY_EVENT));
}

/** The built-in demo shop (sample data, no account): only when the visitor chose it. */
export function isDemo(): boolean {
  try { return typeof window !== "undefined" && window.localStorage.getItem(D) === "1"; } catch { return false; }
}
export function setDemo(on: boolean): void {
  try { if (on) window.localStorage.setItem(D, "1"); else window.localStorage.removeItem(D); } catch { /* private mode */ }
  window.dispatchEvent(new Event(KEY_EVENT));
}

/** Looks like one of our keys: checked before it is stored, so a typo is caught at once. */
export const KEY_SHAPE = /^lf_test_[0-9a-f]{48}$/;
