// The "Landfall connection" box: staff paste the account's secret key; Kiln checks it with Landfall, keeps it on the server, and the checkout then uses that account.
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";

const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "kiln-conn-"));
const GOOD = "lf_test_" + "ab12cd34".repeat(6);
const ENV_KEY = "lf_test_" + "0123456789abcdef".repeat(3);
const PASSWORD = "test-password-123";
let landfall, kiln, base, cookie = "", seen = [];

before(async () => {
  landfall = http.createServer((req, res) => {  // a fake Landfall: knows two keys
    const key = (req.headers.authorization ?? "").replace("Bearer ", "");
    seen.push({ path: req.url, key });
    res.setHeader("Content-Type", "application/json");
    if (![GOOD, ENV_KEY].includes(key)) { res.statusCode = 401; return res.end(JSON.stringify({ detail: "Unknown API key" })); }
    if (req.url === "/api/merchants/me") return res.end(JSON.stringify({ name: key === GOOD ? "Real Pots" : "Kiln & Co.", city: "Leeds", country: "GB", product_count: 3, feed_url: null, last_synced_at: null }));
    if (req.url === "/api/shop") return res.end(JSON.stringify({ countries: [{ country: "US", label: "United States", currency: "USD" }] }));
    res.statusCode = 404; res.end("{}");
  });
  await new Promise((r) => landfall.listen(0, "127.0.0.1", r));
  process.env.KILN_ADMIN_USER = "owner";
  process.env.KILN_ADMIN_PASSWORD = PASSWORD;
  process.env.KILN_DATA_DIR = dataDir;
  process.env.LANDFALL_KILN_API_KEY = ENV_KEY;
  process.env.LANDFALL_API_URL = `http://127.0.0.1:${landfall.address().port}`;
  const m = await import("./server.mjs");
  kiln = http.createServer(m.handle);
  await new Promise((r) => kiln.listen(0, "127.0.0.1", r));
  base = `http://127.0.0.1:${kiln.address().port}`;
  const r = await fetch(base + "/api/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user: "owner", password: PASSWORD }) });
  cookie = r.headers.get("set-cookie").split(";")[0];
});
after(() => { kiln.close(); landfall.close(); fs.rmSync(dataDir, { recursive: true, force: true }); });

const call = (method, body, signedIn = true) => fetch(base + "/api/admin/landfall", { method, headers: { "Content-Type": "application/json", ...(signedIn ? { Cookie: cookie } : {}) }, body: body ? JSON.stringify(body) : undefined });

test("only signed-in staff can read or change the connection", async () => {
  assert.equal((await call("GET", null, false)).status, 401);
  assert.equal((await call("PUT", { secret: GOOD }, false)).status, 401);
  assert.equal((await call("DELETE", null, false)).status, 401);
});

test("before anything is pasted, Kiln uses the demo account from its environment and says so", async () => {
  const j = await (await call("GET")).json();
  assert.equal(j.source, "env");
  assert.equal(j.account.name, "Kiln & Co.");
  assert.match(j.publishable, /^lf_pub_[0-9a-f]{32}$/);
});

test("a key of the wrong shape, a publishable key from another account, and a key Landfall does not know are all refused in plain words, and nothing is saved", async () => {
  for (const [body, re] of [
    [{ secret: "hello" }, /does not look like a Landfall secret key/],
    [{ secret: GOOD, publishable: "lf_pub_" + "0".repeat(32) }, /does not belong to the secret key/],
    [{ secret: GOOD, publishable: "nope" }, /does not look like a Landfall publishable key/],
    [{ secret: "lf_test_" + "f".repeat(48) }, /Landfall does not know that key/],
  ]) {
    const r = await call("PUT", body);
    assert.equal(r.status, 422, JSON.stringify(body));
    assert.match((await r.json()).detail, re);
  }
  assert.equal((await (await call("GET")).json()).source, "env");
  assert.ok(!fs.existsSync(path.join(dataDir, "landfall-connection.json")));
});

test("a good key is checked with Landfall, kept on the server, and the checkout then uses that account: its publishable key, and its key on every call", async () => {
  const r = await call("PUT", { secret: GOOD });
  assert.equal(r.status, 200);
  const j = await r.json();
  assert.equal(j.source, "saved");
  assert.equal(j.account.name, "Real Pots");
  assert.equal(j.secret_prefix, GOOD.slice(0, 12) + "…");
  const cfg = await (await fetch(base + "/api/config")).json();
  assert.equal(cfg.publishableKey, j.publishable);
  seen = [];
  await fetch(base + "/api/countries");
  assert.ok(seen.length && seen.every((s) => s.key === GOOD), "Kiln asks Landfall as the connected account");
  // the secret never reaches a browser: not in the status, the config, the admin page or the checkout page
  for (const text of [JSON.stringify(j), JSON.stringify(cfg), await (await fetch(base + "/admin", { headers: { Cookie: cookie } })).text(), await (await fetch(base + "/checkout")).text()]) assert.ok(!text.includes(GOOD));
});

test("a matching publishable key may be pasted too; disconnecting falls back to the demo account", async () => {
  const pub = (await (await call("GET")).json()).publishable;
  assert.equal((await call("PUT", { secret: GOOD, publishable: pub })).status, 200);
  const j = await (await call("DELETE")).json();
  assert.equal(j.source, "env");
  assert.ok(!fs.existsSync(path.join(dataDir, "landfall-connection.json")));
});

test("when Landfall does not answer, nothing is saved and the message says so", async () => {
  const addr = landfall.address();
  await new Promise((r) => landfall.close(r));
  const r = await call("PUT", { secret: GOOD });
  assert.equal(r.status, 502);
  assert.match((await r.json()).detail, /Landfall did not answer/);
  assert.ok(!fs.existsSync(path.join(dataDir, "landfall-connection.json")));
  void addr;
});
