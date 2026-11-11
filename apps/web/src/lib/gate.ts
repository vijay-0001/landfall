import { createHash, timingSafeEqual } from "node:crypto";

/**
 * The password gate for a public Landfall site. Off unless SITE_PASSWORD is set on the server.
 * Everything is gated except what a merchant's shop needs from a shopper's browser (the checkout widget and the quote call), the public
 * Coverage page, and the gate's own page. Only requests addressed to the PUBLIC host name (the host of PUBLIC_URL) are gated; calls from inside
 * the server network (for example the share-image renderer asking for http://web:3000) are not. If PUBLIC_URL is missing the gate fails closed
 * and covers every request.
 */
export const COOKIE = "lf_gate";

const OPEN_PREFIXES = ["/gate", "/_next", "/api/widget", "/api/health", "/api/coverage", "/coverage"];
const OPEN_EXACT = ["/api/quote", "/favicon.ico"];

export const tokenFor = (password: string): string => createHash("sha256").update(`landfall-gate-v1:${password}`).digest("hex");

export function passwordMatches(given: string, password: string): boolean {
  const a = createHash("sha256").update(given).digest();
  const b = createHash("sha256").update(password).digest();
  return timingSafeEqual(a, b);
}

export type Decision = "allow" | "login" | "deny";

/** A path is open when it is one of the listed paths or lies under one of the listed folders (never a look-alike such as /gateway). */
const isOpen = (path: string): boolean => OPEN_EXACT.includes(path) || OPEN_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`));

/** The host name (no port) of a URL or a Host header, lower case; "" if there is none. */
export const hostOf = (value: string | undefined): string => {
  if (!value) return "";
  try { return new URL(value.includes("://") ? value : `http://${value}`).hostname.toLowerCase(); } catch { return ""; }
};

export function gateDecision(input: { password: string | undefined; path: string; host: string | undefined; publicUrl: string | undefined; cookie: string | undefined }): Decision {
  const { password, path, host, publicUrl, cookie } = input;
  if (!password) return "allow";                       // not configured: an ordinary local or private run
  const pub = hostOf(publicUrl);
  if (pub && hostOf(host) !== pub) return "allow";     // addressed to something other than the public site: inside the server network
  if (isOpen(path)) return "allow";
  if (cookie && cookie === tokenFor(password)) return "allow";
  return path.startsWith("/api/") ? "deny" : "login";
}
