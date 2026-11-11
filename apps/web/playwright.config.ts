import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "@playwright/test";

// E2E runs the real stack locally: Postgres (LANDFALL_TEST_DATABASE_URL), the API, the renderer and the built web app.
const WEB = Number(process.env.E2E_PORT ?? 3100);
const API = Number(process.env.E2E_API_PORT ?? 8100);
const REN = Number(process.env.E2E_RENDERER_PORT ?? 3300);
const KILN = Number(process.env.E2E_KILN_PORT ?? 3410);
const KILN_KEY = "lf_test_" + "0123456789abcdef".repeat(3);  // a throwaway key for the e2e database only
const root = path.resolve(__dirname, "../..");
/** One value from the root .env (never printed). Kiln, the mock merchant, gets the sandbox PayPal app as ITS credentials; Landfall's API server gets none of them here. */
function envValue(name: string): string {
  try {
    const line = fs.readFileSync(path.join(root, ".env"), "utf8").split(/\r?\n/).find((l) => l.startsWith(name + "="));
    return line ? line.slice(name.length + 1).trim() : "";
  } catch { return ""; }
}
// Kiln's back office is on for the e2e run, with a fresh data folder each time (products added by a test never leak into the next run).
const KILN_DATA = path.join(root, "apps/kiln/data-e2e");
const KILN_ADMIN_PASSWORD = "e2e-kiln-staff-pass-1";  // throwaway: the e2e Kiln only
fs.rmSync(KILN_DATA, { recursive: true, force: true });
const SIGNING_KEY = "e2e-signing-key-" + "ab12".repeat(8);  // throwaway, for the e2e database only
// A dedicated database (created on first use, kept between runs so the real recommender is only called for new products).
const dbUrl = process.env.E2E_DATABASE_URL ?? "postgresql+pg8000://postgres:landfall@localhost:55432/landfall_e2e";
const python = process.env.E2E_PYTHON ?? path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results/artifacts",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB}`,
    // The console shows nothing until a store is connected or the built-in demo shop is chosen on purpose. Most journeys test the demo shop, so they start with that choice made;
    // the journeys about connecting a store clear it (kiln.spec.ts).
    storageState: { cookies: [], origins: [{ origin: `http://127.0.0.1:${WEB}`, localStorage: [{ name: "landfall_demo", value: "1" }] }] },
    reducedMotion: "reduce",
    colorScheme: "light",
    locale: "en-GB",
    timezoneId: "UTC",
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn landfall_api.main:app --host 127.0.0.1 --port ${API}`,
      cwd: root,
      url: `http://127.0.0.1:${API}/api/health`,
      env: { RENDERER_URL: `http://127.0.0.1:${REN}`, LANDFALL_DATABASE_URL: dbUrl, LANDFALL_UK_ONDEMAND: "off", LANDFALL_US_ONDEMAND: "off",
        LANDFALL_KILN_API_KEY: KILN_KEY, LANDFALL_ALLOW_PRIVATE_FEEDS: "1", LANDFALL_ALLOW_SIGNUP: "1", LANDFALL_SIGNING_KEY: SIGNING_KEY },
      reuseExistingServer: !process.env.CI,
      timeout: 600_000,
    },
    {
      command: "node server.mjs",
      cwd: path.join(root, "apps/renderer"),
      url: `http://127.0.0.1:${REN}/health`,
      env: { PORT: String(REN), WEB_URL: `http://127.0.0.1:${WEB}` },
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: "node server.mjs",  // the mock merchant: its only link to Landfall is the API and its key
      cwd: path.join(root, "apps/kiln"),
      url: `http://127.0.0.1:${KILN}/health`,
      env: { PORT: String(KILN), LANDFALL_API_URL: `http://127.0.0.1:${API}`, KILN_ADMIN_USER: "owner", KILN_ADMIN_PASSWORD: KILN_ADMIN_PASSWORD, KILN_DATA_DIR: KILN_DATA, LANDFALL_PUBLIC_API_URL: `http://127.0.0.1:${API}`, LANDFALL_CONSOLE_URL: `http://127.0.0.1:${WEB}`, LANDFALL_KILN_API_KEY: KILN_KEY, KILN_PUBLIC_URL: `http://127.0.0.1:${KILN}`,
        KILN_PAYPAL_CLIENT_ID: envValue("PAYPAL_CLIENT_ID"), KILN_PAYPAL_CLIENT_SECRET: envValue("PAYPAL_CLIENT_SECRET") },
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      // Production build, not dev: dev-mode first compiles are slow and flaky on Windows.
      command: `npm run build && npx next start -p ${WEB} -H 127.0.0.1`,
      env: { API_PROXY_TARGET: `http://127.0.0.1:${API}`, API_INTERNAL_URL: `http://127.0.0.1:${API}` },
      url: `http://127.0.0.1:${WEB}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 300_000,
    },
  ],
});
