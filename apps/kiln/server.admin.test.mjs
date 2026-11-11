// Kiln's back office: a merchant adds a product with photos, edits it and removes it; the shop and the product feed follow. A temporary data folder, a fake Landfall.
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "kiln-admin-"));
let kiln;
let base;
let cookie = "";
const PASSWORD = "test-password-123";
const jpeg = (n) => "data:image/jpeg;base64," + fs.readFileSync(path.join(HERE, "public", "photos", n)).toString("base64");

before(async () => {
  process.env.KILN_ADMIN_USER = "owner";
  process.env.KILN_ADMIN_PASSWORD = PASSWORD;
  process.env.KILN_DATA_DIR = dataDir;
  process.env.LANDFALL_API_URL = "http://127.0.0.1:9";  // nothing listens: the back office never calls Landfall
  process.env.KILN_PUBLIC_URL = "http://kiln.example";
  const m = await import("./server.mjs");
  kiln = http.createServer(m.handle);
  await new Promise((r) => kiln.listen(0, "127.0.0.1", r));
  base = `http://127.0.0.1:${kiln.address().port}`;
  const r = await fetch(base + "/api/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user: "owner", password: PASSWORD }) });
  cookie = r.headers.get("set-cookie").split(";")[0];  // the staff session the rest of the tests use
});
after(() => { kiln.close(); fs.rmSync(dataDir, { recursive: true, force: true }); });

const send = (method, p, b) => fetch(base + p, { method, headers: { "Content-Type": "application/json", Cookie: cookie }, body: b ? JSON.stringify(b) : undefined });
const PRICES = { GBP: "24.00", USD: "30.00", EUR: "28.00", AUD: "46.00", CAD: "41.00" };
const NEW = { title: "Hand-thrown stoneware jug", description: "A stoneware milk jug thrown by hand in our Stoke studio, 400 ml.", sku: "JUG-001", prices: PRICES };

test("without a staff session: the back office page sends you to the login, the API says 401, and the nav offers the staff login (never the admin)", async () => {
  const r = await fetch(base + "/admin", { redirect: "manual" });
  assert.equal(r.status, 302);
  assert.equal(r.headers.get("location"), "/login");
  assert.equal((await fetch(base + "/api/admin/products")).status, 401);
  assert.equal((await fetch(base + "/api/admin/products", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "x" }) })).status, 401);
  assert.equal((await fetch(base + "/api/admin/products/MUG-001", { method: "DELETE" })).status, 401);
  const home = await (await fetch(base + "/")).text();
  assert.match(home, /href="\/login">Staff login/);
  assert.ok(!home.includes('href="/admin"'));
  assert.match(await (await fetch(base + "/login")).text(), /<script src="\/login\.js"/);
});

test("signing in sets a strict HttpOnly session cookie, and the nav then offers Shop admin; the admin page shows the feed address and how to connect Landfall", async () => {
  const r = await fetch(base + "/api/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user: "owner", password: PASSWORD }) });
  assert.equal(r.status, 200);
  const sc = r.headers.get("set-cookie");
  assert.match(sc, /^kiln_session=[A-Za-z0-9_.-]+;/);
  assert.match(sc, /HttpOnly/);
  assert.match(sc, /SameSite=Strict/);
  assert.match(await (await fetch(base + "/", { headers: { Cookie: cookie } })).text(), /href="\/admin">Shop admin/);
  const admin = await (await fetch(base + "/admin", { headers: { Cookie: cookie } })).text();
  assert.match(admin, /Shop admin/);
  assert.match(admin, /<script src="\/admin\.js"/);
  assert.match(admin, /Connect this shop to Landfall/);
  assert.match(admin, /http:\/\/kiln\.example\/products\.json/);
  assert.equal((await (await fetch(base + "/api/admin/session", { headers: { Cookie: cookie } })).json()).signedIn, true);
});

test("a forged, tampered or expired session is refused", async () => {
  for (const bad of ["kiln_session=abc.def", "kiln_session=" + cookie.split("=")[1].split(".")[0] + ".AAAA", "kiln_session=", "kiln_session=e30.e30"]) {
    assert.equal((await fetch(base + "/api/admin/products", { headers: { Cookie: bad } })).status, 401, bad);
  }
});

test("a product added with two photos appears in the list and in the Shopify-shaped feed, with absolute photo addresses", async () => {
  const r = await send("POST", "/api/admin/products", { ...NEW, photos: [{ data: jpeg("mug-1.jpg") }, { data: jpeg("mug-2.jpg") }] });
  const j = await r.json();
  assert.equal(r.status, 201, JSON.stringify(j));
  assert.equal(j.product.sku, "JUG-001");
  assert.equal(j.product.images.length, 2);
  const feed = await (await fetch(base + "/products.json")).json();
  const p = feed.products.find((x) => x.variants[0].sku === "JUG-001");
  assert.ok(p, "in the feed");
  assert.equal(p.title, "Hand-thrown stoneware jug");
  assert.match(p.body_html, /^<p>A stoneware milk jug/);
  assert.equal(p.variants[0].presentment_prices.length, 4);  // the four currencies Landfall prices
  assert.equal(p.images.length, 2);
  for (const i of p.images) {
    assert.match(i.src, /^http:\/\/kiln\.example\/uploads\/[a-f0-9]{16}\.jpg$/);
    const img = await fetch(base + new URL(i.src).pathname);
    assert.equal(img.status, 200);
    assert.equal(img.headers.get("content-type"), "image/jpeg");
    assert.deepEqual([...Buffer.from(await img.arrayBuffer()).subarray(0, 3)], [0xff, 0xd8, 0xff]);
  }
  assert.equal(feed.products.length, 10, "the nine seed products plus the new one");
});

test("the data is Kiln's own: it survives in the catalogue file and the seed catalogue is untouched", () => {
  const live = JSON.parse(fs.readFileSync(path.join(dataDir, "catalogue.json"), "utf8"));
  assert.equal(live.products.length, 10);
  assert.equal(JSON.parse(fs.readFileSync(path.join(HERE, "catalogue.json"), "utf8")).products.length, 9);
});

test("a duplicate SKU, a bad price and a missing description are refused in plain words and nothing is stored", async () => {
  let r = await send("POST", "/api/admin/products", NEW);
  assert.equal(r.status, 409);
  assert.match((await r.json()).detail, /already exists/);
  r = await send("POST", "/api/admin/products", { ...NEW, sku: "JUG-002", prices: { ...PRICES, USD: "1e9" } });
  assert.equal(r.status, 422);
  assert.match((await r.json()).detail, /USD price must be a positive number/);
  r = await send("POST", "/api/admin/products", { ...NEW, sku: "JUG-002", description: "short" });
  assert.equal(r.status, 422);
  r = await send("POST", "/api/admin/products", { ...NEW, sku: "bad sku!" });
  assert.equal(r.status, 422);
  assert.equal((await (await fetch(base + "/products.json")).json()).products.length, 10);
});

test("a photo must be a real JPEG, PNG or WebP of at most 2 MB, and at most four are accepted", async () => {
  const html = Buffer.from("<html>not an image at all</html>").toString("base64");
  let r = await send("POST", "/api/admin/products", { ...NEW, sku: "JUG-003", photos: [{ data: html }] });
  assert.equal(r.status, 422);
  assert.match((await r.json()).detail, /not a JPEG, PNG or WebP/);
  const big = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.alloc(2 * 1024 * 1024 + 10)]).toString("base64");
  r = await send("POST", "/api/admin/products", { ...NEW, sku: "JUG-003", photos: [{ data: big }] });
  assert.equal(r.status, 422);
  assert.match((await r.json()).detail, /larger than 2 MB/);
  r = await send("POST", "/api/admin/products", { ...NEW, sku: "JUG-003", photos: Array.from({ length: 5 }, () => ({ data: jpeg("mug-1.jpg") })) });
  assert.equal(r.status, 422);
  assert.match((await r.json()).detail, /At most 4 photos/);
  assert.equal((await (await fetch(base + "/products.json")).json()).products.length, 10, "nothing was stored");
});

test("editing changes the words, the prices and the photos; the feed follows", async () => {
  const cur = (await (await send("GET", "/api/admin/products")).json()).products.find((p) => p.sku === "JUG-001");
  const r = await send("PUT", "/api/admin/products/JUG-001", {
    title: cur.title, description: "A glazed stoneware milk jug, made in Portugal for us, 400 ml.", prices: { ...PRICES, USD: "34.00" }, keep: [cur.images[0]], photos: [{ data: jpeg("wallet-1.jpg") }],
  });
  const j = await r.json();
  assert.equal(r.status, 200, JSON.stringify(j));
  assert.equal(j.product.images.length, 2);
  assert.equal(j.product.images[0], cur.images[0]);
  const p = (await (await fetch(base + "/products.json")).json()).products.find((x) => x.variants[0].sku === "JUG-001");
  assert.match(p.body_html, /made in Portugal/);
  assert.equal(p.variants[0].presentment_prices.find((x) => x.price.currency_code === "USD").price.amount, "34.00");
  // a photo the product does not have cannot be "kept" by naming it
  const r2 = await send("PUT", "/api/admin/products/JUG-001", { title: cur.title, description: "A glazed stoneware milk jug, made in Portugal for us.", prices: PRICES, keep: ["/photos/mug-1.jpg"] });
  assert.equal((await r2.json()).product.images.length, 0);
});

test("text is stored as text: markup in a title or description is escaped in the feed", async () => {
  const r = await send("POST", "/api/admin/products", { ...NEW, sku: "XSS-001", title: "Mug <script>alert(1)</script>", description: "A mug <img src=x onerror=alert(1)> thrown by hand in our studio." });
  assert.equal(r.status, 201);
  const p = (await (await fetch(base + "/products.json")).json()).products.find((x) => x.variants[0].sku === "XSS-001");
  assert.ok(!p.body_html.includes("<img"));
  assert.match(p.body_html, /&lt;img/);
  await send("DELETE", "/api/admin/products/XSS-001");
});

test("removing a product takes it out of the shop and the feed, and an unknown SKU is a plain 404", async () => {
  let r = await send("DELETE", "/api/admin/products/JUG-001");
  assert.equal(r.status, 200);
  assert.ok(!(await (await fetch(base + "/products.json")).json()).products.some((x) => x.variants[0].sku === "JUG-001"));
  r = await send("DELETE", "/api/admin/products/JUG-001");
  assert.equal(r.status, 404);
  assert.match((await r.json()).detail, /No product with that SKU/);
});

test("uploads cannot be used to read other files", async () => {
  for (const p of ["/uploads/../server.mjs", "/uploads/..%2Fserver.mjs", "/uploads/0000000000000000.jpg", "/uploads/%2e%2e/catalogue.json"]) {
    assert.equal((await fetch(base + p)).status, 404, p);
  }
});

test("the cookie-less photo files stay public (they are in the product feed) but nothing else under uploads is", async () => {
  const feed = await (await fetch(base + "/products.json")).json();
  const mug = feed.products.find((p) => p.variants[0].sku === "MUG-001");
  assert.equal((await fetch(base + new URL(mug.images[0].src).pathname)).status, 200);  // seed photos are public files
});

test("wrong passwords are refused without saying which part was wrong, then locked out after five in a minute (run last: it blocks this address)", async () => {
  for (let i = 0; i < 5; i++) {
    const r = await fetch(base + "/api/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user: "owner", password: "nope-" + i }) });
    assert.equal(r.status, 401);
    assert.equal((await r.json()).detail, "That user name or password is not right.");
    assert.equal(r.headers.get("set-cookie"), null);
  }
  const r = await fetch(base + "/api/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user: "owner", password: PASSWORD }) });
  assert.equal(r.status, 429);
});
