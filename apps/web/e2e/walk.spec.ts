import { expect, test, type Page } from "@playwright/test";

// The first-time-user walk, one journey per gap found: each persona, each step, "what do I do next, and does it work?". They run last, on the same database.
const KILN = `http://127.0.0.1:${process.env.E2E_KILN_PORT ?? 3410}`;
const KILN_STAFF_PASSWORD = "e2e-kiln-staff-pass-1";  // the throwaway staff password playwright.config.ts gives the e2e Kiln

test.beforeEach(async ({ page }) => {
  // a first-time visitor: no store, no demo choice (cleared once per test, not on every navigation)
  await page.addInitScript(() => { try { if (!window.sessionStorage.getItem("__walk")) { window.localStorage.clear(); window.sessionStorage.setItem("__walk", "1"); } } catch { /* ignore */ } });
});

const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

/** A product page whose recommendation asks the origin question. The real recommender asks it only when its two reads disagree, which a fresh run may not do, so the page's own
 *  requests are answered here (the real round trip is covered by the API tests and by hand in Chrome). The posted answers are recorded. */
async function mockOriginQuestion(page: Page, request: import("@playwright/test").APIRequestContext) {
  const real = await (await request.get("/api/products/p_wallet")).json();
  const usd = (a: string) => ({ amount: a, currency: "USD" });
  const q = { id: "q_origin", trigger: "T4", text: "We could not find a strong sign of where this was made. Where was it made?", options: [
    { id: "origin_GB", label: "United Kingdom", is_ai_pick: true, price_impact: usd("0.00") }, { id: "origin_CN", label: "China", is_ai_pick: false, price_impact: usd("4.10") },
    { id: "origin_other", label: "Somewhere else", is_ai_pick: false, price_impact: null }] };
  const detail = { ...real, product: { ...real.product, id: "p_origin", review_status: "not_reviewed", question_count: 1 }, recommendation: { ...real.recommendation, questions: [q] } };
  const posted: string[] = [];
  await page.route("**/api/products/p_origin", (route) => route.fulfill({ json: detail }));
  await page.route("**/api/recommendations/*/answer", async (route) => {
    const oid = route.request().postDataJSON().option_id as string;
    posted.push(oid);
    const m = /^origin_([A-Z]{2})$/.exec(oid);
    const options = [...q.options]; // the server adds a named country to the question, as the real answer endpoint does
    if (m && !options.some((o) => o.id === oid)) options.splice(options.length - 1, 0, { id: oid, label: "Vietnam", is_ai_pick: false, price_impact: usd("0.60") });
    await route.fulfill({ json: { recommendation: { ...detail.recommendation, questions: [{ ...q, options }] }, remaining_questions: 0 } });
  });
  return posted;
}

test("W1. a first-time seller: a country list not a code box, plain errors, the keys explained, an empty store that says what to do, and a way out", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/products");
  await expect(page).toHaveURL(/\/connect\?needs=store/);
  const ships = page.getByLabel("Ships from");
  await expect(ships).toHaveJSProperty("tagName", "SELECT");  // no one has to know ISO codes
  await expect(ships.locator("option", { hasText: "United Kingdom" })).toHaveCount(1);
  await expect(ships.locator("option", { hasText: "Greece" })).toHaveCount(1);
  // a validation failure from the server is read in plain words, never "[object Object]"
  await page.route("**/api/merchants", (route) => (route.request().method() === "POST"
    ? route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: [{ type: "string_too_short", loc: ["body", "city"], msg: "String should have at least 2 characters" }] }) })
    : route.continue()));
  await page.getByLabel("Shop name").fill("Walk Pots");
  await page.getByLabel("City").fill("Leeds");
  await page.getByRole("button", { name: "Open account" }).click();
  const err = page.locator(".note-bar.stop");
  await expect(err).toContainText("city: String should have at least 2 characters");
  await expect(err).not.toContainText("[object");
  await page.unroute("**/api/merchants");
  const name = `Walk Pots ${Date.now() % 100000}`;
  await page.getByLabel("Shop name").fill(name);
  await page.getByRole("button", { name: "Open account" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  // the first page after sign-up is about the store, not about keys; the keys have their own page in the nav, which says what they are for
  await expect(page.getByLabel("Feed address")).toBeVisible();
  await expect(page.locator("main")).not.toContainText("lf_pub_");
  await page.getByRole("link", { name: "API keys" }).first().click();
  await expect(page.getByRole("heading", { name: "API keys" })).toBeVisible();
  await expect(page.locator("main")).toContainText("script in your merchant portal");
  await expect(page.locator("#publishable-key")).toHaveText(/^lf_pub_[0-9a-f]{32}$/);
  await expect(page.locator("#secret-key")).not.toContainText("lf_test_" + "0".repeat(10));  // hidden until asked for
  await page.getByRole("button", { name: "Show secret key" }).click();
  await expect(page.locator("#secret-key")).toHaveText(/^lf_test_[0-9a-f]{48}$/);
  await page.goto("/connect");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  // a connected store with nothing imported says what to do, with a link that goes there
  await page.goto("/products");
  await expect(page.getByText("No products yet")).toBeVisible({ timeout: 20_000 });
  await page.getByRole("link", { name: /Connect your store.s feed/ }).click();
  await expect(page).toHaveURL(/\/connect$/);
  // an address that is not a product: a way back, not a pointless retry
  await page.goto("/products/nonsense");
  await expect(page.getByRole("link", { name: "Back to products" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toHaveCount(0);
  // phone width
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/connect");
  expect(await noSideScroll(page)).toBeLessThanOrEqual(1);
  // sign out leads to Connect store (not to a demo shop the visitor never chose)
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.goto("/products");
  await expect(page).toHaveURL(/\/connect\?needs=store/);
});

test("W2. a decision can be changed: Accepted has a Change my decision button, Override offers only countries Landfall prices (plus a plain 'not priced yet'), and evidence is a reference, not a file that goes nowhere", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/connect");
  await page.getByRole("button", { name: "Open the built-in demo shop" }).click();
  await page.goto("/products/p_mug");
  await expect(page.getByRole("button", { name: "Change my decision" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Change my decision" }).click();
  await page.getByRole("button", { name: "Override" }).click();
  const origin = page.getByLabel("Country of origin");
  const options = await origin.locator("option").allTextContents();
  expect(options).toContain("United Kingdom");
  expect(options).toContain("A country Landfall does not price yet");
  for (const bad of ["Canada", "Mexico", "United States"]) expect(options).not.toContain(bad);  // not priced, so never offered as if it were
  await expect(page.getByLabel("Your evidence reference (optional)")).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await origin.selectOption({ label: "A country Landfall does not price yet" });
  await expect(page.getByText("Landfall adds no duty for this product")).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Keep my earlier decision" }).click();
  await expect(page.getByRole("button", { name: "Change my decision" })).toBeVisible();  // nothing was saved
});

for (const [tag, size] of [["desktop", { width: 1440, height: 900 }], ["phone", { width: 390, height: 844 }]] as const) {
  test(`W3. 'Somewhere else' is a country list (${tag}): name any country Landfall prices, or one it does not, and the answer is sent`, async ({ page, request }) => {
    await page.setViewportSize(size);
    await page.goto("/connect");
    await page.getByRole("button", { name: "Open the built-in demo shop" }).click();
    const posted = await mockOriginQuestion(page, request);
    await page.goto("/products/p_origin/questions");
    const pick = page.getByLabel("Another country of origin");
    await expect(pick).toBeVisible({ timeout: 20_000 });
    await expect(pick.locator("option", { hasText: "Vietnam" })).toHaveCount(1, { timeout: 20_000 });  // the list is read from the coverage endpoint
    const opts = await pick.locator("option").allTextContents();
    expect(opts).toContain("Vietnam");
    expect(opts).toContain("A country Landfall does not price yet");
    expect(opts.length).toBeGreaterThan(8);  // the twelve covered origins, minus the ones already offered as buttons
    for (const bad of ["Canada", "Mexico"]) expect(opts).not.toContain(bad);
    await pick.selectOption({ label: "Vietnam" });
    await expect.poll(() => posted).toContain("origin_VN");
    await expect(page.getByRole("radio", { name: /Vietnam/ })).toBeChecked({ timeout: 20_000 });  // it joins the question's options, with its price effect
    await pick.selectOption({ label: "A country Landfall does not price yet" });
    await expect.poll(() => posted).toContain("origin_other");
    expect(await noSideScroll(page)).toBeLessThanOrEqual(1);
  });
}

test("W4. Kiln's Landfall connection: staff paste the account's keys, Kiln checks them with Landfall, and the shop and checkout then say only what that account has priced", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const name = `Connect Pots ${Date.now() % 100000}`;
  const m = await (await request.post("/api/merchants", { data: { name, country: "GB", city: "Stoke" } })).json();
  const auth = { Authorization: `Bearer ${m.api_key}` };
  await page.goto(`${KILN}/login`);
  await page.getByLabel("User name").fill("owner");
  await page.getByLabel("Password").fill(KILN_STAFF_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/admin$/);
  const status = page.locator("#conn-status");
  await expect(status).toContainText(/demo account from the server's settings/, { timeout: 20_000 });
  await page.setViewportSize({ width: 390, height: 800 });  // the connection box fits a phone too
  expect(await noSideScroll(page)).toBeLessThanOrEqual(1);
  await page.setViewportSize({ width: 1440, height: 900 });
  // refusals are plain, and nothing is saved
  await page.locator("#conn-secret").fill("hello");
  await page.getByRole("button", { name: "Check and save" }).click();
  await expect(page.locator("#conn-msg")).toContainText("does not look like a Landfall secret key");
  await page.locator("#conn-secret").fill(m.api_key);
  await page.locator("#conn-pub").fill("lf_pub_" + "0".repeat(32));
  await page.getByRole("button", { name: "Check and save" }).click();
  await expect(page.locator("#conn-msg")).toContainText("does not belong to the secret key");
  await page.locator("#conn-pub").fill("");
  await page.locator("#conn-secret").fill("lf_test_" + "f".repeat(48));
  await page.getByRole("button", { name: "Check and save" }).click();
  await expect(page.locator("#conn-msg")).toContainText("Landfall does not know that key");
  // the real key: checked, saved, the field emptied, the secret never in the page
  await page.locator("#conn-secret").fill(m.api_key);
  await page.getByRole("button", { name: "Check and save" }).click();
  await expect(status).toContainText(`Connected to the Landfall account "${name}"`, { timeout: 20_000 });
  await expect(status).toContainText("0 products");
  await expect(page.locator("#conn-secret")).toHaveValue("");
  expect(await page.content()).not.toContain(m.api_key);
  // nothing synced yet: the shop says it is being set up and nothing can be ordered, instead of a checkout that fails
  await page.goto(KILN);
  await expect(page.locator("#shop-lead")).toContainText("still being set up", { timeout: 20_000 });
  await expect(page.getByRole("button", { name: /Add Hand-thrown stoneware mug to cart/ })).toBeDisabled();
  await expect(page.locator("#grid .item", { hasText: "Hand-thrown stoneware mug" })).toContainText("Not available to order yet");
  // the account imports Kiln's feed: products can be ordered, but no duty is promised until the seller accepts
  const imp = await request.post("/api/products/import", { headers: auth, data: { feed_url: `${KILN}/products.json`, currency: "GBP" } });
  expect(imp.ok(), await imp.text()).toBeTruthy();
  await page.goto(KILN);
  const mug = page.locator("#grid .item", { hasText: "Hand-thrown stoneware mug" });
  await expect(mug).toContainText("Import duty is not included", { timeout: 20_000 });
  await expect(mug.getByText("Duties included")).toHaveCount(0);
  await expect(page.locator("#shop-lead")).toContainText("not included in these prices yet");
  await page.evaluate(() => { localStorage.setItem("kiln_cart", JSON.stringify([{ sku: "MUG-001", quantity: 1 }])); localStorage.setItem("kiln_ship", "US"); });
  await page.goto(`${KILN}/checkout`);
  const sum = page.locator("#landfall .lf-summary");
  await expect(sum).toContainText("No duty is added to this order", { timeout: 30_000 });
  await expect(sum).toContainText("Not added");
  await expect(sum).not.toContainText("included");  // never claims duties included when nothing was priced
  // the seller accepts the mug (an identical listing reuses a recommendation: no model call): now the same mug is priced
  const cat = await (await request.get("/api/catalogue", { headers: auth })).json();
  const row = cat.products.find((p: { sku: string }) => p.sku === "MUG-001");
  const detail = await (await request.post(`/api/products/${row.id}/recommend`, { headers: auth })).json();
  const ok = await request.post(`/api/recommendations/${detail.recommendation.id}/decision`, { headers: auth, data: { action: "accepted", fine_print_version: detail.fine_print_version } });
  expect(ok.status()).toBe(200);
  await page.goto(`${KILN}/checkout`);
  await expect(sum).toContainText("Import duties and taxes, included", { timeout: 30_000 });
  await expect(sum).toContainText("$7.60");
  await page.goto(KILN);
  await expect(page.locator("#grid .item", { hasText: "Hand-thrown stoneware mug" }).getByText("Duties included")).toBeVisible({ timeout: 20_000 });
  // a product added in Kiln's back office is marked as not in Landfall yet, and a shopper cannot order it
  const added = await page.request.post(`${KILN}/api/admin/products`, { data: { title: "Walk linen tea towel", description: "Linen tea towel, woven and sewn by hand in our Leeds studio.", sku: "TEA-777", prices: { GBP: "12.00", USD: "15.00", EUR: "14.00", AUD: "23.00" } } });
  expect(added.status()).toBe(201);
  await page.goto(KILN);
  await expect(page.getByRole("button", { name: /Add Walk linen tea towel to cart/ })).toBeDisabled({ timeout: 20_000 });
  await page.goto(`${KILN}/admin`);
  await expect(page.locator('#plist li[data-sku="TEA-777"]')).toContainText("Not in Landfall yet", { timeout: 20_000 });
  await page.request.delete(`${KILN}/api/admin/products/TEA-777`);
  // a stale cart holding an unavailable product loses it with a plain note, and the rest checks out
  await page.evaluate(() => localStorage.setItem("kiln_cart", JSON.stringify([{ sku: "MUG-001", quantity: 1 }, { sku: "GONE-1", quantity: 1 }])));
  await page.goto(`${KILN}/checkout`);
  await expect(page.locator("#cart-note")).toContainText("taken out of your cart", { timeout: 20_000 });
  await expect(sum).toContainText("$7.60", { timeout: 30_000 });
  // disconnect: back to the demo account from the server's settings
  await page.goto(`${KILN}/admin`);
  await page.getByRole("button", { name: "Disconnect" }).click();
  await expect(status).toContainText(/demo account from the server's settings/, { timeout: 20_000 });
  await page.getByRole("button", { name: "Sign out" }).click();
});

test("W5. a key Landfall does not know is refused where it is pasted, and a saved key that stops working leads to a new sign-in, not a dead end", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/connect");
  await page.getByLabel("API key").fill("lf_test_" + "a".repeat(48));
  await page.getByRole("button", { name: "Sign in with this key" }).click();
  await expect(page.locator(".note-bar.stop")).toContainText("Landfall does not know that key");
  expect(await page.evaluate(() => localStorage.getItem("landfall_api_key"))).toBeNull();  // never kept
  // a key that was valid and no longer is (a database reset, a key from another deployment)
  await page.evaluate(() => localStorage.setItem("landfall_api_key", "lf_test_" + "b".repeat(48)));
  await page.goto("/products");
  await expect(page.getByRole("link", { name: "Sign in again" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("link", { name: "Sign in again" }).click();
  await expect(page).toHaveURL(/\/connect/);
  expect(await page.evaluate(() => localStorage.getItem("landfall_api_key"))).toBeNull();  // forgotten, so the connect page is the clean way in
  await expect(page.getByRole("button", { name: "Open account" })).toBeVisible();
});

test("W6. the passport share link and badge are the seller's own, not the demo shop's", async ({ page, request }) => {
  const m = await (await request.post("/api/merchants", { data: { name: `Badge Pots ${Date.now() % 100000}`, country: "GB", city: "Leeds" } })).json();
  const me = await (await request.get("/api/passport", { headers: { Authorization: `Bearer ${m.api_key}` } })).json();
  expect(me.badge_image_url).toBe(`/api/passport/badge.png?shop=${m.shop_id}`);
  const png = await request.get(me.badge_image_url);
  expect(png.status()).toBe(200);
  expect(png.headers()["content-type"]).toBe("image/png");
  await page.setViewportSize({ width: 1200, height: 630 });
  await page.goto(me.share_url);
  await expect(page.locator("#share-card")).toContainText(m.name);
});
