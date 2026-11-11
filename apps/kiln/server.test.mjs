// Kiln's own tests: its feed, config, and validate-then-capture, against a fake Landfall and a fake PayPal (localhost only, no real network).
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { after, before, beforeEach, test } from "node:test";

const KEY = "lf_test_0123456789abcdef";
const seen = [];
// Scenario knobs the tests flip.
const world = { paypalOrderStatus: "APPROVED", verify: { status: 200, body: { valid: true, reasons: [] } }, landfallDown: false, captureStatus: "COMPLETED" };

const order = (status) => ({
  id: "5O190127TN364715T", status,
  purchase_units: [{ amount: { currency_code: "USD", value: "59.60", breakdown: { tax_total: { currency_code: "USD", value: "7.60" } } }, items: [{ name: "Mug", sku: "MUG-001", quantity: "1", unit_amount: { currency_code: "USD", value: "38.00" }, tax: { currency_code: "USD", value: "7.60" } }] }],
});

const fake = http.createServer((req, res) => {
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    seen.push({ method: req.method, url: req.url, auth: req.headers.authorization, body: body.startsWith("{") ? JSON.parse(body) : null });
    res.setHeader("Content-Type", "application/json");
    const json = (code, o) => { res.statusCode = code; res.end(JSON.stringify(o)); };
    if (req.url === "/v1/oauth2/token") return json(200, { access_token: "fake-token", expires_in: 3000 });
    if (req.url === "/v2/checkout/orders/5O190127TN364715T" && req.method === "GET") return json(200, order(world.paypalOrderStatus));
    if (req.url === "/v2/checkout/orders/5O190127TN364715T/capture") {
      // PayPal's real capture answer: no amount on the purchase unit, the amount sits on the capture
      const o = order(world.captureStatus);
      delete o.purchase_units[0].amount;
      o.purchase_units[0].payments = { captures: [{ id: "CAP123456789", status: "COMPLETED", amount: { currency_code: "USD", value: "59.60" } }] };
      return json(201, o);
    }
    if (req.url === "/api/quotes/verify") return json(world.verify.status, world.verify.body);
    if (req.url === "/api/shop") return json(200, { countries: [{ country: "US", name: "United States", destination: "US", currency: "USD" }] });
    if (req.url === "/api/catalogue") return json(200, { products: [{ sku: "MUG-001", review_status: "accepted", code: "6912.00.44.00", origin: "GB", band: "High", paused_reason: null }] });
    json(404, {});
  });
});
let kiln;
let base;
let mod;

before(async () => {
  await new Promise((r) => fake.listen(0, "127.0.0.1", r));
  const root = `http://127.0.0.1:${fake.address().port}`;
  process.env.KILN_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "kiln-main-"));  // never the real data folder: a key saved there must not leak into the tests
  process.env.LANDFALL_API_URL = root;
  process.env.LANDFALL_PUBLIC_API_URL = "http://landfall.example";
  process.env.LANDFALL_KILN_API_KEY = KEY;
  process.env.KILN_PAYPAL_BASE = root;
  process.env.KILN_PAYPAL_CLIENT_ID = "public-client-id";
  process.env.KILN_PAYPAL_CLIENT_SECRET = "very-secret-paypal-value";
  mod = await import("./server.mjs");
  kiln = http.createServer(mod.handle);
  await new Promise((r) => kiln.listen(0, "127.0.0.1", r));
  base = `http://127.0.0.1:${kiln.address().port}`;
});
after(() => { kiln.close(); fake.close(); });
beforeEach(() => {
  seen.length = 0;
  world.paypalOrderStatus = "APPROVED";
  world.verify = { status: 200, body: { valid: true, reasons: [] } };
  world.captureStatus = "COMPLETED";
});

const post = (p, b) => fetch(base + p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
const captures = () => seen.filter((s) => s.url.endsWith("/capture")).length;
const GOOD = { order_id: "5O190127TN364715T", quote_token: "t".repeat(40) };

test("the feed is Shopify-shaped, has a SKU on every variant, and leaks none of Kiln's own styling fields", async () => {
  const j = await (await fetch(base + "/products.json")).json();
  assert.equal(j.products.length, 9);
  for (const p of j.products) {
    assert.ok(p.title && p.body_html && !("colour" in p));
    assert.ok(p.variants.every((v) => v.sku && v.presentment_prices.length >= 4));
    assert.ok(Array.isArray(p.images) && p.images.every((i) => /\/photos\/[a-z0-9-]+\.jpg$/.test(i.src)), "pictures are in Shopify's images[].src shape");
  }
  assert.equal(j.products[0].variants[0].sku, "MUG-001");
});

test("/api/config exposes only public values: the publishable key, the PayPal client id and the Landfall address", async () => {
  const text = await (await fetch(base + "/api/config")).text();
  const j = JSON.parse(text);
  assert.equal(j.landfallApi, "http://landfall.example");
  assert.equal(j.paypalClientId, "public-client-id");
  assert.match(j.publishableKey, /^lf_pub_[0-9a-f]{32}$/);
  assert.ok(!text.includes(KEY) && !text.includes("very-secret"), "no secret may appear in the config");
});

test("the publishable key matches Landfall's derivation (fixed vector, same as the Python test)", () => {
  assert.equal(mod.publishableKey(KEY), "lf_pub_6ed87c794658b06df6bf95bd18090f5c");
});

test("happy path: the order is fetched, verified by Landfall with the secret key, then captured exactly once", async () => {
  const r = await post("/api/validate", GOOD);
  const j = await r.json();
  assert.equal(r.status, 200);
  assert.equal(j.status, "captured");
  assert.equal(j.receipt.capture_id, "CAP123456789");
  assert.equal(j.receipt.total, "59.60");
  assert.equal(j.receipt.tax_total, "7.60");
  assert.equal(captures(), 1);
  const v = seen.find((s) => s.url === "/api/quotes/verify");
  assert.equal(v.auth, `Bearer ${KEY}`);
  assert.equal(v.body.quote_token, GOOD.quote_token);
  assert.equal(v.body.paypal_order.id, "5O190127TN364715T");
  assert.ok(!JSON.stringify(j).includes(KEY) && !JSON.stringify(j).includes("very-secret"), "the browser never sees a secret");
  assert.ok(j.exchanges.length === 3);
});

test("a mismatch (verify says valid:false) means status changed and NO capture", async () => {
  world.verify = { status: 200, body: { valid: false, reasons: ["The tax total differs from the quote"] } };
  const j = await (await post("/api/validate", GOOD)).json();
  assert.equal(j.status, "changed");
  assert.deepEqual(j.reasons, ["The tax total differs from the quote"]);
  assert.equal(captures(), 0);
});

test("an expired or forged quote (verify answers 422) is also 'changed' and nothing is captured", async () => {
  world.verify = { status: 422, body: { detail: "The quote has expired" } };
  const j = await (await post("/api/validate", GOOD)).json();
  assert.equal(j.status, "changed");
  assert.match(j.reasons[0], /expired/);
  assert.equal(captures(), 0);
});

test("an order that is not APPROVED gets 409, Landfall is not asked and nothing is captured", async () => {
  world.paypalOrderStatus = "CREATED";
  const r = await post("/api/validate", GOOD);
  assert.equal(r.status, 409);
  assert.equal(captures(), 0);
  assert.equal(seen.filter((s) => s.url === "/api/quotes/verify").length, 0);
});

test("Landfall failing gives an error and no capture", async () => {
  world.verify = { status: 500, body: { detail: "boom" } };
  const r = await post("/api/validate", GOOD);
  assert.equal(r.status, 502);
  assert.equal((await r.json()).status, "error");
  assert.equal(captures(), 0);
});

test("Landfall not answering at all gives an error and no capture", async () => {
  // Point a second Kiln at a closed port.
  const closed = http.createServer();
  await new Promise((r) => closed.listen(0, "127.0.0.1", r));
  const dead = closed.address().port;
  await new Promise((r) => closed.close(r));
  const old = process.env.LANDFALL_API_URL;
  // The module reads its env at import: re-import with a dead Landfall.
  process.env.LANDFALL_API_URL = `http://127.0.0.1:${dead}`;
  const m3 = await import("./server.mjs?down=1");
  process.env.LANDFALL_API_URL = old;
  const out = await m3.validate(GOOD);
  assert.notEqual(out.body.status, "captured");
  assert.equal(captures(), 0);
});

for (const [name, body] of [
  ["no body", {}],
  ["a bad order id", { order_id: "../../etc", quote_token: "t".repeat(40) }],
  ["a missing token", { order_id: "5O190127TN364715T" }],
  ["a huge token", { order_id: "5O190127TN364715T", quote_token: "t".repeat(5000) }],
  ["numbers instead of strings", { order_id: 5, quote_token: 7 }],
]) {
  test(`bad input gets 422 and touches nothing: ${name}`, async () => {
    const r = await post("/api/validate", body);
    assert.equal(r.status, 422);
    assert.equal(seen.length, 0);
  });
}

test("what Landfall holds is listed for the inspector", async () => {
  const j = await (await fetch(base + "/api/known")).json();
  assert.equal(j.products[0].sku, "MUG-001");
  assert.match(j.exchange.auth, /^Bearer lf_test_.{0,6}…$/);
});

test("every product photo is served as a real JPEG, and most products have more than one photo or at least one", async () => {
  const j = await (await fetch(base + "/products.json")).json();
  let withPhotos = 0;
  for (const p of j.products) {
    if (p.images.length) withPhotos += 1;
    for (const i of p.images) {
      const r = await fetch(base + new URL(i.src).pathname);
      assert.equal(r.status, 200);
      assert.match(r.headers.get("content-type"), /image\/jpeg/);
      const b = Buffer.from(await r.arrayBuffer());
      assert.deepEqual([...b.subarray(0, 3)], [0xff, 0xd8, 0xff], "the bytes are a JPEG, not a placeholder");
      assert.ok(b.length > 20_000, "a real photograph, not a drawing");
    }
  }
  assert.equal(withPhotos, 9);  // every product has photos
  assert.equal(j.products.find((p) => p.variants[0].sku === "MUG-001").images.length, 2);
});

test("the photo credits are served beside the photos", async () => {
  const r = await fetch(base + "/photos/CREDITS.md");
  assert.equal(r.status, 200);
  const t = await r.text();
  assert.match(t, /Unsplash License/);
  assert.equal((t.match(/\.jpg \|/g) ?? []).length, 18, "every photo is credited to its photographer");
});

test("static files cannot escape the public folder", async () => {
  assert.equal((await fetch(base + "/..%2Fserver.mjs")).status, 404);
  assert.equal((await fetch(base + "/kiln.css")).status, 200);
});

test("the product page is served, every feed handle is linkable, and the page carries the shop script", async () => {
  const r = await fetch(base + "/product?h=mug-001");
  assert.equal(r.status, 200);
  const html = await r.text();
  assert.match(html, /id="product"/);
  assert.match(html, /\/kiln\.js/);
  const feed = await (await fetch(base + "/products.json")).json();
  for (const p of feed.products) assert.ok(p.handle, `${p.title} has a handle for its page`);
});

test("the old Landfall-hosted paths are gone", async () => {
  assert.equal((await post("/api/pay", {})).status, 404);
  assert.equal((await fetch(base + "/return")).status, 404);
});

test("the config carries the console address for the footer link to Coverage and sources", async () => {
  const j = await (await fetch(base + "/api/config")).json();
  assert.ok(j.consoleUrl, "consoleUrl is public and set");
});

test("the back office is OFF unless a password is set: no admin page, no login, no admin API, no uploads", async () => {
  assert.equal((await fetch(base + "/admin")).status, 404);
  assert.equal((await fetch(base + "/login")).status, 404);
  assert.equal((await post("/api/admin/login", { user: "owner", password: "anything-at-all" })).status, 404);
  assert.equal((await fetch(base + "/api/admin/products")).status, 404);
  assert.equal((await post("/api/admin/products", { title: "x" })).status, 404);
  assert.equal((await fetch(base + "/uploads/0000000000000000.jpg")).status, 404);
  const home = await (await fetch(base + "/")).text();
  assert.ok(!home.includes("Shop admin") && !home.includes("Staff login"));
});
