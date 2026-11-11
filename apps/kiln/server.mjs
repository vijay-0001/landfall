// Kiln & Co.: a MOCK MERCHANT, separate from Landfall. A small online shop with its own catalogue, cart and pages.
//
// How it uses Landfall (this is the integration a real merchant would do):
//   1. Its checkout page loads Landfall's widget script. The widget asks Landfall for the duty (POST /api/quote, with a PUBLISHABLE, quote-only key),
//      shows the duty line and the total, and renders the PayPal button with Kiln's PUBLIC PayPal client ID. The PayPal order is built from Landfall's tax lines.
//   2. When the buyer approves at PayPal no money has moved. The widget calls Kiln's own endpoint, POST /api/validate (below). It is the one piece of back-end work:
//      Kiln's server fetches the approved order from PayPal with KILN'S OWN PayPal credentials, asks Landfall to verify the order against the signed quote
//      (POST /api/quotes/verify, with Kiln's secret key), and only if it matches does it capture. A mismatch means nothing is captured.
//   Landfall never holds a PayPal credential. Kiln's secret keys never reach the browser.
// Also: GET /products.json is Kiln's catalogue in Shopify's feed shape; Landfall imports it.
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createAdmin } from "./admin.mjs";
import { createConnection, publishableKey, PUBLISHABLE_SHAPE, SECRET_SHAPE } from "./connection.mjs";

export { publishableKey };

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT ?? 3400);
const API = (process.env.LANDFALL_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const PUBLIC_API = (process.env.LANDFALL_PUBLIC_API_URL ?? API).replace(/\/$/, ""); // where the BROWSER reaches Landfall
const CONSOLE = (process.env.LANDFALL_CONSOLE_URL ?? PUBLIC_API).replace(/\/$/, ""); // where the BROWSER reaches Landfall's console pages
const KEY = process.env.LANDFALL_KILN_API_KEY ?? "";
const PP_BASE = (process.env.KILN_PAYPAL_BASE ?? "https://api-m.sandbox.paypal.com").replace(/\/$/, "");
const PP_ID = process.env.KILN_PAYPAL_CLIENT_ID ?? "";
const PP_SECRET = process.env.KILN_PAYPAL_CLIENT_SECRET ?? "";
// The merchant's back office (add products and photos): a mock, off unless KILN_ADMIN=1. The catalogue it edits is Kiln's own file; the seed catalogue is catalogue.json.
const DATA_DIR = process.env.KILN_DATA_DIR ?? path.join(HERE, "data");
// Which Landfall account Kiln's checkout asks: pasted by staff in the shop admin and kept here on the server; LANDFALL_KILN_API_KEY is the fallback (the demo account).
const CONN = createConnection({ dataDir: DATA_DIR, envKey: KEY });
const ADMIN = createAdmin({ dataDir: DATA_DIR, seedPath: path.join(HERE, "catalogue.json"), user: process.env.KILN_ADMIN_USER || "owner", password: process.env.KILN_ADMIN_PASSWORD ?? "" });
const CONSOLE_URL = (process.env.LANDFALL_CONSOLE_URL ?? PUBLIC_API).replace(/\/$/, "");
const FEED_URL = (process.env.KILN_PUBLIC_URL ?? `http://127.0.0.1:${PORT}`).replace(/\/$/, "") + "/products.json";
const MIME = { ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".md": "text/markdown; charset=utf-8" };

export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** The feed a store serves: Kiln's own fields (colour) stay out of it. */
export function feed() {
  const base = (process.env.KILN_PUBLIC_URL ?? `http://127.0.0.1:${PORT}`).replace(/\/$/, "");
  return { products: ADMIN.load().products.map(({ colour, images, ...p }) => ({ ...p, images: (images ?? []).map((src) => ({ src: base + src })) })) };  // Shopify's shape: images[].src
}

/** One call to Landfall, recorded for the inspector. The Authorization header shows the key's prefix only. */
export async function landfall(method, route, body, key = CONN.current().secret) {
  const t = Date.now();
  let status = 0;
  let json = null;
  if (!key) {  // nothing to send: say so plainly instead of asking Landfall with an empty key
    json = { detail: "Kiln is not connected to a Landfall account yet. Staff: sign in to the shop admin and add the keys under Landfall connection." };
    return { status: 503, json, exchange: { method, path: route, auth: "no key set", request: body ?? null, status: 503, response: json, ms: 0 } };
  }
  try {
    const r = await fetch(API + route, {
      method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(60_000),
    });
    status = r.status;
    json = await r.json().catch(() => null);
  } catch (e) {
    json = { detail: "Landfall did not answer. " + (e?.message ?? "") };
  }
  return { status, json, exchange: { method, path: route, auth: `Bearer ${key.slice(0, 12)}…`, request: body ? { ...body, paypal_order: body.paypal_order ? "(the PayPal order, as PayPal returned it)" : undefined } : null, status, response: json, ms: Date.now() - t } };
}

/** One call to PayPal with Kiln's OWN credentials (the merchant's, not Landfall's). The inspector gets a short summary, not the raw order. */
let ppToken = null;
async function paypalToken() {
  if (ppToken && ppToken.exp > Date.now() + 60_000) return ppToken.value;
  const r = await fetch(PP_BASE + "/v1/oauth2/token", {
    method: "POST",
    headers: { Authorization: "Basic " + Buffer.from(`${PP_ID}:${PP_SECRET}`).toString("base64"), "Content-Type": "application/x-www-form-urlencoded" },
    body: "grant_type=client_credentials",
    signal: AbortSignal.timeout(30_000),
  });
  const j = await r.json().catch(() => null);
  if (!r.ok || !j?.access_token) throw new Error("PayPal refused Kiln's credentials");
  ppToken = { value: j.access_token, exp: Date.now() + (j.expires_in ?? 300) * 1000 };
  return ppToken.value;
}

export async function paypal(method, route, body, requestId) {
  const t = Date.now();
  let status = 0;
  let json = null;
  try {
    const r = await fetch(PP_BASE + route, {
      method,
      headers: { Authorization: "Bearer " + (await paypalToken()), "Content-Type": "application/json", ...(requestId ? { "PayPal-Request-Id": requestId } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(30_000),
    });
    status = r.status;
    json = await r.json().catch(() => null);
  } catch (e) {
    json = { message: e?.message ?? "PayPal did not answer" };
  }
  const unit = json?.purchase_units?.[0];
  const summary = unit ? { id: json.id, status: json.status, amount: unit.amount, items: (unit.items ?? []).map((i) => ({ sku: i.sku, quantity: i.quantity, tax: i.tax })) } : json;
  return { status, json, exchange: { method, path: route, auth: "Kiln's own PayPal credentials (server-side)", request: null, status, response: summary, ms: Date.now() - t } };
}

let countries = null;
async function shipTo() {
  if (countries?.length) return countries;  // an empty answer (Landfall down, no key yet) is never remembered
  const r = await landfall("GET", "/api/shop");
  countries = r.json?.countries ?? [];
  return countries;
}

function readBody(req, limit = 50_000) {
  return new Promise((resolve, reject) => {
    let b = "";
    req.on("data", (c) => { b += c; if (b.length > limit) { reject(new Error("too large")); req.destroy(); } });
    req.on("end", () => { try { resolve(b ? JSON.parse(b) : {}); } catch { reject(new Error("bad json")); } });
  });
}

const send = (res, code, body, type = "application/json; charset=utf-8") => { res.writeHead(code, { "Content-Type": type, "Cache-Control": "no-store" }); res.end(typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body)); };

/**
 * The merchant's one piece of back-end work: validate, then capture.
 * The buyer has approved at PayPal and no money has moved. Fetch the order with Kiln's own credentials, have Landfall check it against the signed quote,
 * and capture only if it matches. On any mismatch nothing is captured and the buyer is asked to review a fresh quote.
 */
export async function validate(b) {
  const exchanges = [];
  const orderId = b?.order_id;
  const token = b?.quote_token;
  if (typeof orderId !== "string" || !/^[A-Za-z0-9-]{8,40}$/.test(orderId) || typeof token !== "string" || token.length < 10 || token.length > 4000) {
    return { code: 422, body: { status: "error", message: "That order could not be checked. Nothing was charged." } };
  }
  const got = await paypal("GET", `/v2/checkout/orders/${orderId}`);
  exchanges.push(got.exchange);
  if (got.status !== 200 || !got.json) return { code: 502, body: { status: "error", message: "PayPal could not find the order. Nothing was charged.", exchanges } };
  if (got.json.status !== "APPROVED") return { code: 409, body: { status: "error", message: "The order is not approved at PayPal yet. Nothing was charged.", exchanges } };
  const v = await landfall("POST", "/api/quotes/verify", { quote_token: token, paypal_order: got.json });
  exchanges.push(v.exchange);
  if (v.status === 422) return { code: 200, body: { status: "changed", reasons: [v.json?.detail ?? "The quote is not valid"], exchanges } };  // expired, forged or not ours
  if (v.status !== 200 || !v.json) return { code: 502, body: { status: "error", message: "Landfall could not check the order. Nothing was charged.", exchanges } };
  if (!v.json.valid) return { code: 200, body: { status: "changed", reasons: v.json.reasons, exchanges } };  // nothing is captured
  const cap = await paypal("POST", `/v2/checkout/orders/${orderId}/capture`, {}, `kiln-capture-${orderId}`);
  exchanges.push(cap.exchange);
  const unit = cap.json?.purchase_units?.[0];
  const c = unit?.payments?.captures?.[0];
  if (![200, 201].includes(cap.status) || cap.json?.status !== "COMPLETED" || !c) return { code: 502, body: { status: "error", message: "PayPal could not complete the payment. Nothing was charged.", exchanges } };
  // The money has moved from here on: never answer "nothing was charged". PayPal's capture answer carries the amount on the capture, not on the purchase unit,
  // so the receipt is read from the capture plus the order Kiln fetched before capturing.
  const before = got.json.purchase_units?.[0] ?? {};
  const amount = c.amount ?? unit?.amount ?? before.amount ?? {};
  const items = unit?.items ?? before.items ?? [];
  return {
    code: 200,
    body: {
      status: "captured",
      receipt: {
        order_id: cap.json.id, capture_id: c.id, currency: amount.currency_code ?? before.amount?.currency_code ?? "", total: amount.value ?? before.amount?.value ?? "",
        tax_total: before.amount?.breakdown?.tax_total?.value ?? unit?.amount?.breakdown?.tax_total?.value ?? "0.00",
        items: items.map((i) => ({ name: i.name, quantity: i.quantity, unit: i.unit_amount?.value, tax: i.tax?.value })),
      },
      exchanges,
    },
  };
}

/** What the connection box shows: which account Kiln asks for duties, and whether Landfall knows its key. Public values and a key prefix only. */
async function connectionStatus() {
  const cur = CONN.current();
  const out = { source: cur.source, secret_prefix: cur.secret ? cur.secret.slice(0, 12) + "…" : "", publishable: cur.publishable, account: null, problem: null };
  if (!cur.secret) { out.problem = "No Landfall account is connected: Kiln's checkout cannot add duty yet."; return out; }
  const r = await landfall("GET", "/api/merchants/me");
  if (r.status === 200) out.account = { name: r.json.name, city: r.json.city, country: r.json.country, product_count: r.json.product_count, feed_url: r.json.feed_url, last_synced_at: r.json.last_synced_at };
  else out.problem = r.status === 401 ? "Landfall does not recognise the key Kiln is using." : "Landfall did not answer.";
  return out;
}

const page = (title, body, signedIn = false, script = "kiln") => `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title><link rel="stylesheet" href="/kiln.css"></head>
<body>
<div class="demo-strip">Kiln &amp; Co. is a make-believe shop. It uses Landfall, an AI duties service, to price import duty. PayPal sandbox only.</div>
<header class="top"><a class="brand" href="/">Kiln &amp; Co.</a><span class="tag">Hand-made pottery, Stoke-on-Trent</span>
<nav>${ADMIN.enabled ? (signedIn ? '<a class="navlink" href="/admin">Shop admin</a>' : '<a class="navlink" href="/login">Staff login</a>') : ""}${script === "kiln" ? `<label class="shipto">Ship to <select id="shipto" aria-label="Ship to country"></select></label>
<a class="cart" id="cartlink" href="/checkout">Cart (<span id="cartcount">0</span>)</a>` : '<a class="navlink" href="/">Back to the shop</a>'}</nav></header>
${body}
<footer class="foot">Import duties and taxes are calculated by <strong>Landfall</strong>. <a id="coverage-link" href="/products.json">Coverage and sources</a>${ADMIN.enabled ? (signedIn ? ' · <a href="/admin">Shop admin</a>' : ' · <a href="/login">Staff login</a>') : ""}</footer>
<script src="/${script}.js" defer></script></body></html>`;

const PRODUCT = `<main class="wrap" id="product"><p class="lead">Loading…</p></main>`;
const SHOP = `<main class="wrap"><h1>The studio shop</h1><p class="lead" id="shop-lead">Checking which prices include duty…</p>
<ul class="grid" id="grid" aria-live="polite"></ul></main>`;
const adminPage = () => `<main class="wrap" id="admin"><div class="adm-head"><h1>Shop admin</h1><button id="logout" class="mini" type="button">Sign out</button></div><p class="lead">Kiln's back office (a make-believe one, with a staff login). Products and photos you add here appear in the shop and in Kiln's product feed. Landfall reads the feed; it never sees this page or stores the photos.</p>
<section class="connect" aria-labelledby="connect-title"><h2 id="connect-title">Connect this shop to Landfall</h2><p>Landfall prices import duty. Two steps, once.</p>
<ol><li><b>Give Landfall this shop's product feed.</b> Open <a href="${esc(CONSOLE_URL)}/connect">Landfall's Connect store page</a>, open an account, paste this feed address and press <b>Import products</b>:<br><code id="feed-url">${esc(FEED_URL)}</code></li>
<li><b>Connect Kiln's checkout to that account.</b> In Landfall open <a href="${esc(CONSOLE_URL)}/keys">API keys</a>, copy the secret key and paste it in the box below. Then Kiln's checkout asks <i>that</i> account for duties, on the products it has synced and you have accepted.</li></ol>
<p class="muted">After you add or change a product here, press <b>Sync now</b> in Landfall (<a href="${esc(CONSOLE_URL)}/products">Products</a>); Landfall also syncs every night.</p></section>
<section class="connect" aria-labelledby="keys-title" id="landfall-connection"><h2 id="keys-title">Landfall connection</h2>
<div id="conn-status" class="note" role="status">Checking the connection…</div>
<form id="conn-form" class="aform" aria-label="Landfall keys">
<label>Secret key<input id="conn-secret" type="password" autocomplete="off" spellcheck="false" placeholder="lf_test_…"><small>Stays on Kiln's server. Kiln's server uses it to ask Landfall to check each PayPal order before it captures the payment. It is never sent to a browser.</small></label>
<label>Publishable key (optional to paste)<input id="conn-pub" autocomplete="off" spellcheck="false" placeholder="lf_pub_…"><small>Goes in the checkout page: the widget uses it to ask for the duty on a cart, and for nothing else. It is worked out from the secret key; if you paste one, Kiln checks they match.</small></label>
<div id="conn-msg" class="note warn" role="alert" hidden></div>
<div class="actions"><button id="conn-save" class="btn" type="submit">Check and save</button><button id="conn-clear" class="btn ghost" type="button" hidden>Disconnect</button></div></form></section>
<div class="adm-two"><section aria-labelledby="form-title"><h2 id="form-title">Add a product</h2>
<form id="pform" class="aform" aria-label="Product form">
<label>Title<input id="title" required minlength="3" maxlength="120" autocomplete="off"></label>
<label>Description<textarea id="description" required minlength="10" maxlength="2000" rows="4"></textarea><small>Say what it is made of and where it is made.</small></label>
<label>SKU (optional)<input id="sku" maxlength="24" placeholder="made from the title if blank" autocomplete="off"></label>
<fieldset><legend>Price in each currency</legend><div class="prices">${["GBP", "USD", "EUR", "AUD"].map((c) => `<label>${c}<input id="price-${c}" inputmode="decimal" required placeholder="0.00"></label>`).join("")}</div></fieldset>
<div><label class="filebtn">Add photos<input id="photos" type="file" accept="image/jpeg,image/png,image/webp" multiple></label> <span id="photo-count" class="muted">0 of 4 photos</span></div>
<div id="photo-preview" class="previews"></div>
<div id="msg" class="note" role="status" hidden></div>
<div class="actions"><button id="submit" class="btn" type="submit">Add product</button><button id="cancel" class="btn ghost" type="button" hidden>Cancel</button></div>
</form></section>
<section aria-labelledby="plist-title"><h2 id="plist-title">Products <span id="count" class="muted"></span></h2><ul id="plist" class="plist" aria-live="polite"></ul></section></div></main>`;
const LOGIN_PAGE = `<main class="wrap narrow" id="login"><h1>Staff login</h1><p class="lead">For Kiln &amp; Co.'s own staff. Shoppers do not need an account to buy.</p>
<form id="lform" class="aform" aria-label="Staff login"><label>User name<input id="user" autocomplete="username" required></label><label>Password<input id="password" type="password" autocomplete="current-password" required></label>
<div id="lmsg" class="note warn" role="alert" hidden></div><div class="actions"><button class="btn" type="submit">Sign in</button></div></form></main>`;
const CHECKOUT = `<main class="wrap two" id="checkout"><section aria-labelledby="co"><h1 id="co">Checkout</h1><div id="lines"></div><div id="landfall"></div><div id="receipt" aria-live="polite"></div></section>
<aside class="inspector" id="inspector" aria-labelledby="insp"><h2 id="insp">How Landfall is used here</h2><p class="muted">What the checkout widget asked Landfall, and what Kiln's server did after the buyer approved. Kiln's secret keys stay on its server.</p><div id="calls"></div></aside></main>`;

export async function handle(req, res) {
  const u = new URL(req.url, "http://x");
  try {
    if (req.method === "GET" && u.pathname === "/health") return send(res, 200, { status: "ok" });
    if (req.method === "GET" && u.pathname === "/") return send(res, 200, page("Kiln & Co.", SHOP, ADMIN.signedIn(req)), "text/html; charset=utf-8");
    if (req.method === "GET" && u.pathname === "/product") return send(res, 200, page("Kiln & Co.", PRODUCT, ADMIN.signedIn(req)), "text/html; charset=utf-8");
    if (req.method === "GET" && u.pathname === "/checkout") return send(res, 200, page("Checkout · Kiln & Co.", CHECKOUT, ADMIN.signedIn(req)), "text/html; charset=utf-8");
    if (req.method === "GET" && u.pathname === "/login" && ADMIN.enabled) return send(res, 200, page("Staff login · Kiln & Co.", LOGIN_PAGE, ADMIN.signedIn(req), "login"), "text/html; charset=utf-8");
    if (req.method === "GET" && u.pathname === "/admin" && ADMIN.enabled) {
      if (!ADMIN.signedIn(req)) { res.writeHead(302, { Location: "/login" }); return res.end(); }
      return send(res, 200, page("Shop admin · Kiln & Co.", adminPage(), true, "admin"), "text/html; charset=utf-8");
    }
    if (u.pathname === "/api/admin/landfall" && ADMIN.enabled) {  // the Landfall connection box: staff only, the secret never leaves the server
      if (!ADMIN.signedIn(req)) return send(res, 401, { detail: "Sign in to the shop admin first." });
      if (req.method === "GET") return send(res, 200, await connectionStatus());
      if (req.method === "DELETE") { CONN.clear(); countries = null; return send(res, 200, await connectionStatus()); }
      if (req.method === "PUT") {
        let b;
        try { b = await readBody(req, 2000); } catch { return send(res, 422, { detail: "That request could not be read." }); }
        const secret = String(b?.secret ?? "").trim();
        const pub = String(b?.publishable ?? "").trim();
        if (!SECRET_SHAPE.test(secret)) return send(res, 422, { detail: "That does not look like a Landfall secret key. It starts with lf_test_ and is 56 characters; Landfall shows it once when the account is opened." });
        if (pub && !PUBLISHABLE_SHAPE.test(pub)) return send(res, 422, { detail: "That does not look like a Landfall publishable key. It starts with lf_pub_ and is 39 characters." });
        if (pub && pub !== publishableKey(secret)) return send(res, 422, { detail: "That publishable key does not belong to the secret key you pasted. Both keys come from the same Landfall account." });
        const check = await landfall("GET", "/api/merchants/me", undefined, secret);  // a real call: a key Landfall does not know is refused here, not at the first checkout
        if (check.status === 401) return send(res, 422, { detail: "Landfall does not know that key. Check it was copied whole, or open a new account in Landfall." });
        if (check.status !== 200) return send(res, 502, { detail: "Landfall did not answer, so the key could not be checked. Nothing was saved." });
        CONN.save(secret);
        countries = null;
        return send(res, 200, await connectionStatus());
      }
    }
    if (await ADMIN.handle(req, res, u, { send, readBody })) return;
    if (req.method === "GET" && u.pathname === "/products.json") return send(res, 200, feed());
    if (req.method === "GET" && u.pathname === "/api/countries") return send(res, 200, await shipTo());
    if (req.method === "GET" && u.pathname === "/api/config") return send(res, 200, { landfallApi: PUBLIC_API, consoleUrl: CONSOLE, publishableKey: CONN.current().publishable, paypalClientId: PP_ID });  // all public values
    if (req.method === "GET" && u.pathname === "/api/known") {  // what Landfall holds for Kiln's products: shown in the inspector
      const r = await landfall("GET", "/api/catalogue");
      const rows = (r.json?.products ?? []).map((p) => ({ sku: p.sku, review_status: p.review_status, code: p.code, origin: p.origin, band: p.band, paused_reason: p.paused_reason }));
      return send(res, r.status === 200 ? 200 : 502, { products: rows, exchange: r.exchange });
    }
    if (req.method === "POST" && u.pathname === "/api/validate") {
      let b;
      try { b = await readBody(req); } catch { return send(res, 422, { status: "error", message: "That order could not be checked. Nothing was charged." }); }
      const r = await validate(b);
      return send(res, r.code, r.body);
    }
    if (req.method === "GET" && /^\/[\w.-]+\.(css|js|svg|png)$/.test(u.pathname)) {
      const f = path.join(HERE, "public", path.basename(u.pathname));
      if (fs.existsSync(f)) return send(res, 200, fs.readFileSync(f), MIME[path.extname(f)]);
    }
    if (req.method === "GET" && /^\/photos\/[\w.-]+\.(jpg|md)$/.test(u.pathname)) {  // the shop's product photos (and their credits)
      const f = path.join(HERE, "public", "photos", path.basename(u.pathname));
      if (fs.existsSync(f)) return send(res, 200, fs.readFileSync(f), MIME[path.extname(f)]);
    }
    send(res, 404, { detail: "Not found" });
  } catch (e) {
    send(res, 500, { detail: "Kiln hit a problem: " + (e?.message ?? "unknown") });
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  if (!CONN.current().secret) console.warn("No Landfall key yet (LANDFALL_KILN_API_KEY is not set): staff add one in the shop admin, under Landfall connection");
  if (!PP_ID || !PP_SECRET) console.warn("KILN_PAYPAL_CLIENT_ID and KILN_PAYPAL_CLIENT_SECRET are not set: Kiln cannot capture payments");
  http.createServer(handle).listen(PORT, () => console.log(`Kiln & Co. on :${PORT}, Landfall at ${API}`));
}
