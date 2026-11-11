// Kiln's "Landfall connection": which Landfall account Kiln's checkout asks for duties.
// Staff paste the account's secret key in the shop admin; it is kept on Kiln's server (a file in its data folder), never sent to a browser.
// The publishable key is derived from the secret (Landfall's own derivation), so the widget on the checkout page always matches the account.
// Without a saved key Kiln falls back to LANDFALL_KILN_API_KEY (the demo account set in the server's environment).
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

export const SECRET_SHAPE = /^lf_test_[0-9a-f]{48}$/;
export const PUBLISHABLE_SHAPE = /^lf_pub_[0-9a-f]{32}$/;

/** A publishable key that can sit in a web page and cannot be turned back into the secret (the same derivation Landfall uses). */
export const publishableKey = (secret) => "lf_pub_" + crypto.createHash("sha256").update("publishable:" + secret).digest("hex").slice(0, 32);

export function createConnection({ dataDir, envKey = "" }) {
  const file = path.join(dataDir, "landfall-connection.json");
  const saved = () => {
    try { const k = JSON.parse(fs.readFileSync(file, "utf8")).secret; return SECRET_SHAPE.test(k) ? k : ""; } catch { return ""; }
  };
  return {
    /** The key Kiln's server uses right now, and where it came from. */
    current() {
      const s = saved();
      if (s) return { secret: s, publishable: publishableKey(s), source: "saved" };
      if (envKey) return { secret: envKey, publishable: publishableKey(envKey), source: "env" };
      return { secret: "", publishable: "", source: "none" };
    },
    save(secret) {
      fs.mkdirSync(dataDir, { recursive: true });
      fs.writeFileSync(file + ".tmp", JSON.stringify({ secret, saved_at: new Date().toISOString() }), { mode: 0o600 });
      fs.renameSync(file + ".tmp", file);
    },
    clear() { try { fs.rmSync(file, { force: true }); } catch { /* nothing saved */ } },
  };
}
