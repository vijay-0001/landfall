// Share-image renderer. GET /render?path=/share/time-machine?product=..  ->  image/png (1200x630).
// Only /share/* pages of our own web app can be rendered (no open proxy). Results are cached for ten minutes.
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const WEB = process.env.WEB_URL ?? "http://127.0.0.1:3000";
const PORT = Number(process.env.PORT ?? 3300);
const TTL_MS = 10 * 60 * 1000;
const cache = new Map();
let browser;

export function allowed(path) {
  return typeof path === "string" && /^\/share\/[a-z-]+(\?[\w=&.%:-]*)?$/.test(path);
}

// A share page that did not load must never become an image: a screenshot of an error page would be cached and shared.
export function assertRenderable(status) {
  if (!(status >= 200 && status < 300)) throw new Error(`the share page answered HTTP ${status}`);
}

async function render(path) {
  const hit = cache.get(path);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.png;
  browser ??= await chromium.launch({ args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
  try {
    const page = await ctx.newPage();
    const resp = await page.goto(WEB + path, { waitUntil: "networkidle", timeout: 20000 });
    assertRenderable(resp?.status());
    await page.waitForSelector("#share-card, h1", { timeout: 10000 });
    await page.evaluate(() => document.fonts.ready);
    const png = await page.screenshot({ type: "png", clip: { x: 0, y: 0, width: 1200, height: 630 } });
    cache.set(path, { at: Date.now(), png });
    if (cache.size > 200) cache.delete(cache.keys().next().value);
    return png;
  } finally {
    await ctx.close();
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  http.createServer(async (req, res) => {
    const u = new URL(req.url, "http://x");
    if (u.pathname === "/health") { res.end("ok"); return; }
    if (u.pathname !== "/render") { res.statusCode = 404; res.end(); return; }
    const path = u.searchParams.get("path");
    if (!allowed(path)) { res.statusCode = 400; res.end("path not allowed"); return; }
    try {
      const t = Date.now();
      const png = await render(path);
      res.setHeader("Content-Type", "image/png");
      res.setHeader("Cache-Control", "public, max-age=3600");
      res.setHeader("X-Render-Ms", String(Date.now() - t));
      res.end(png);
    } catch (e) {
      res.statusCode = 502; res.end(String(e.message ?? e));
    }
  }).listen(PORT, () => console.log(`renderer on :${PORT}, web at ${WEB}`));
}
