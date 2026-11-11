import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Kiln & Co. is a mock merchant: a separate app that reaches Landfall only through the API with its own key. These journeys run the real stack:
// Kiln's server -> Landfall's API -> the real register -> the PayPal sandbox (create-order only: approval needs a sandbox login nobody types here).
const KILN = `http://127.0.0.1:${process.env.E2E_KILN_PORT ?? 3410}`;
const envValue = (name: string): string => {  // from the root .env, never printed
  try { const l = fs.readFileSync(path.resolve(__dirname, "../../../.env"), "utf8").split(/\r?\n/).find((x) => x.startsWith(name + "=")); return l ? l.slice(name.length + 1).trim() : ""; } catch { return ""; }
};
const KILN_STAFF_PASSWORD = "e2e-kiln-staff-pass-1";  // the throwaway staff password playwright.config.ts gives the e2e Kiln
const KILN_KEY = "lf_test_" + "0123456789abcdef".repeat(3);  // the same constant playwright.config.ts gives both servers

test.beforeEach(async ({ page }) => {
  // clear once per test and origin (a marker in sessionStorage), not on every navigation: the cart must survive going from the shop to checkout
  await page.addInitScript(() => { try { if (!window.sessionStorage.getItem("__e2e")) { window.localStorage.clear(); window.sessionStorage.setItem("__e2e", "1"); } } catch { /* ignore */ } });
});

const add = (page: Page, title: string) => page.getByRole("button", { name: `Add ${title} to cart` }).click();
const ship = (page: Page, country: string) => page.locator("#shipto").selectOption(country);

test("K1. Kiln's shop: nine products, prices follow the country, the vase cannot be sold and says why", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(KILN);
  await expect(page.locator("#grid .item")).toHaveCount(9, { timeout: 20_000 });
  // real photographs (Unsplash, credited): every product has two (a thumbnail swaps the main photo)
  await expect(page.locator("#grid .item .tile.photo a.imglink > img")).toHaveCount(9);
  expect(await page.locator("#grid .tile.photo a.imglink > img").evaluateAll((els) => els.every((e) => (e as HTMLImageElement).complete && (e as HTMLImageElement).naturalWidth >= 800))).toBe(true);
  const mugCard = page.locator("#grid .item", { hasText: "Hand-thrown stoneware mug" });
  await expect(mugCard.locator(".thumb")).toHaveCount(2);
  const before = await mugCard.locator(".tile.photo a.imglink > img").getAttribute("src");
  await mugCard.locator(".thumb").nth(1).click();
  expect(await mugCard.locator(".tile.photo a.imglink > img").getAttribute("src")).not.toBe(before);
  const mug = page.locator("#grid .item", { hasText: "Hand-thrown stoneware mug" });
  await expect(mug.getByText("$38.00")).toBeVisible();
  await ship(page, "FR");
  await expect(mug.getByText("€35.00")).toBeVisible();
  await ship(page, "AU");
  await expect(mug.getByText("A$58.00")).toBeVisible();
  const vase = page.locator("#grid .item", { hasText: "uranium" });
  await expect(vase.getByText(/Cannot be sold here/)).toBeVisible();
  await expect(vase.locator(".note.warn")).toContainText(/radioactive/i);
  await expect(vase.getByRole("button", { name: /Add Vintage uranium glass vase to cart/ })).toBeDisabled();
  await expect(page.getByText(/make-believe shop/)).toBeVisible();  // Kiln says it is a mock merchant
});

const sum = (page: Page) => page.locator("#landfall .lf-summary");
const duty = (page: Page) => page.locator("#landfall .lf-duty span").last();
const checkoutWith = async (page: Page, items: { sku: string; quantity: number }[], country = "US") => {
  await page.goto(KILN);
  await page.evaluate(([i, c]) => { localStorage.setItem("kiln_cart", JSON.stringify(i)); localStorage.setItem("kiln_ship", c as string); }, [items, country] as const);
  await page.goto(`${KILN}/checkout`);
};

test("K2. checkout with the widget: the mug to the US is $59.60 with $7.60 duty, the PayPal button renders, the panel shows the widget's call", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(KILN);
  await add(page, "Hand-thrown stoneware mug");
  await page.getByRole("link", { name: /Cart \(1\)/ }).click();
  await expect(sum(page).getByText("$59.60 USD")).toBeVisible({ timeout: 30_000 });
  await expect(duty(page)).toHaveText("$7.60");
  await expect(sum(page).getByText(/calculated by Landfall/)).toBeVisible();
  await expect(page.locator("#landfall .lf-pay iframe").first()).toBeAttached({ timeout: 30_000 });  // PayPal's own button, from PayPal's SDK
  const insp = page.locator("#inspector");
  await expect(insp.getByText("/api/quote")).toBeVisible();
  await expect(insp.getByText(/X-Landfall-Key: lf_pub_/i)).toBeVisible();  // the publishable key, shown as a prefix
  await expect(insp.getByText("The widget sends")).toBeVisible();
  await expect(insp.getByText("MUG-001").first()).toBeVisible();
  await expect(insp.getByText("6912.00.44.00").first()).toBeVisible();
  await expect(sum(page)).not.toContainText("null");
});

test("K3. no secret reaches the page: secret keys are absent from the source and the config, the publishable key is present", async ({ page, request }) => {
  await checkoutWith(page, [{ sku: "MUG-001", quantity: 1 }]);
  await expect(sum(page).getByText("$59.60 USD")).toBeVisible({ timeout: 30_000 });
  const html = await page.content();
  const config = await (await request.get(`${KILN}/api/config`)).text();
  const secrets = [KILN_KEY, envValue("PAYPAL_CLIENT_SECRET"), envValue("ANTHROPIC_API_KEY")].filter((s) => s.length > 8);
  for (const s of secrets) { expect(html).not.toContain(s); expect(config).not.toContain(s); }
  expect(config).toMatch(/"publishableKey":"lf_pub_[0-9a-f]{32}"/);
  expect(await page.locator("#inspector").innerText()).not.toContain(KILN_KEY);
});

test("K4. changing the country re-quotes: France is priced in euros, and the panel shows the new call", async ({ page }) => {
  await checkoutWith(page, [{ sku: "MUG-001", quantity: 1 }]);
  await expect(sum(page).getByText("$59.60 USD")).toBeVisible({ timeout: 30_000 });
  await ship(page, "FR");
  await expect(sum(page).getByText(/€[\d.]+ EUR/)).toBeVisible({ timeout: 30_000 });
  await expect(sum(page)).not.toContainText("USD");
  await expect(page.locator("#inspector").getByText(/"ship_to_country": "FR"/).first()).toBeVisible();
});

test("K5. quantity three and a mixed two-origin cart add up to the cent, and fast clicks never leave a stale quote", async ({ page }) => {
  await checkoutWith(page, [{ sku: "MUG-001", quantity: 3 }]);
  await expect(sum(page).getByText("$150.80 USD")).toBeVisible({ timeout: 30_000 });
  await expect(duty(page)).toHaveText("$22.80");
  await page.goto(KILN);
  await page.getByRole("button", { name: "Add Leather card wallet to cart" }).click();
  await page.goto(`${KILN}/checkout`);
  const mugRow = page.locator("#lines li", { hasText: "Hand-thrown stoneware mug" });
  await expect(mugRow).toContainText("3");
  await mugRow.getByRole("button", { name: "One fewer Hand-thrown stoneware mug" }).click();
  await mugRow.getByRole("button", { name: "One fewer Hand-thrown stoneware mug" }).click();  // two clicks in a row: only the last quote may be shown
  await expect(sum(page).getByText("$97.43 USD")).toBeVisible({ timeout: 30_000 });  // mug 7.60 + wallet 11.83
  await expect(duty(page)).toHaveText("$19.43");
  await page.waitForTimeout(1500);
  await expect(sum(page).getByText("$97.43 USD")).toBeVisible();
});

test("K6. error states are plain: an item Landfall will not price, Landfall not answering, and a bad order handed to Kiln's server", async ({ page, request }) => {
  await checkoutWith(page, [{ sku: "VAS-001", quantity: 1 }]);
  await expect(page.locator("#landfall .lf-msg")).toContainText(/cannot|not price|will not/i, { timeout: 30_000 });
  await expect(page.locator("#landfall .lf-pay iframe")).toHaveCount(0);
  // Landfall not answering
  await page.route("**/api/quote", (route) => route.abort());
  await checkoutWith(page, [{ sku: "MUG-001", quantity: 1 }]);
  await expect(page.locator("#landfall .lf-msg")).toContainText(/did not answer. Nothing was charged/, { timeout: 30_000 });
  await page.unroute("**/api/quote");
  // Kiln's server: bad input and an order PayPal does not know capture nothing and say so
  const bad = await request.post(`${KILN}/api/validate`, { data: { order_id: "x", quote_token: "y" } });
  expect(bad.status()).toBe(422);
  expect((await bad.json()).message).toMatch(/Nothing was charged/);
  const unknown = await request.post(`${KILN}/api/validate`, { data: { order_id: "5O190127TN364715T", quote_token: "t".repeat(40) } });
  expect([502, 409]).toContain(unknown.status());
  expect((await unknown.json()).message).toMatch(/Nothing was charged/);
  // a forged quote token is refused by Landfall itself
  const direct = await request.post(`http://127.0.0.1:${process.env.E2E_API_PORT ?? 8100}/api/quotes/verify`, { headers: { Authorization: `Bearer ${KILN_KEY}` }, data: { quote_token: "forged.token.value", paypal_order: {} } });
  expect(direct.status()).toBe(422);
});

test("K7. at phone width the shop, the checkout, the widget and the panel fit with no sideways scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto(KILN);
  await expect(page.locator("#grid .item")).toHaveCount(9, { timeout: 20_000 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await add(page, "Hand-thrown stoneware mug");
  await page.goto(`${KILN}/checkout`);
  await expect(sum(page).getByText("$59.60 USD")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#landfall .lf-pay iframe").first()).toBeAttached({ timeout: 30_000 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: "test-results/kiln-phone-checkout.png", fullPage: true });
});

test("K8. a merchant signs up, imports Kiln's feed, sees only its own catalogue, and prices by SKU with its own key", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/connect");
  await page.getByRole("button", { name: "Open the built-in demo shop" }).click();  // a deliberate choice: sample data, no account
  await expect(page.getByText("Ready for duties-included")).toBeVisible({ timeout: 20_000 });
  await page.goto("/connect");
  const name = `Acme Glassworks ${Date.now() % 100000}`;
  await page.getByLabel("Shop name").fill(name);
  await page.getByLabel("City").fill("Leeds");
  await page.getByRole("button", { name: "Open account" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("landfall_api_key") ?? "")).not.toBe("");  // the account is opened asynchronously
  const key = await page.evaluate(() => localStorage.getItem("landfall_api_key") ?? "");
  expect(key).toMatch(/^lf_test_[0-9a-f]{48}$/);
  await page.getByLabel("Feed address").fill(`${KILN}/products.json`);
  await page.getByRole("button", { name: "Import products" }).click();
  await expect(page.getByText("Imported 9 products.")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("region", { name: "Imported products" }).getByText("MUG-001")).toBeVisible();
  // the console is now this merchant's: nothing accepted yet, nothing from Kiln's demo shop
  await page.goto("/products");
  await expect(page.getByText("0 of 9")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(name).first()).toBeVisible();
  // by SKU with the key: before the seller accepts anything, no duty is promised
  const auth = { Authorization: `Bearer ${key}` };
  const q0 = await (await request.post("/api/quote", { headers: auth, data: { destination: "US", currency: "USD", ship_to_country: "US", items: [{ sku: "MUG-001" }] } })).json();
  expect(q0.duties_included).toBe(false);
  // the seller asks for the recommendation (an identical listing is reused, so no model call) and accepts it
  const cat = await (await request.get("/api/catalogue", { headers: auth })).json();
  const mug = cat.products.find((p: { sku: string }) => p.sku === "MUG-001");
  const detail = await (await request.post(`/api/products/${mug.id}/recommend`, { headers: auth })).json();
  const ok = await request.post(`/api/recommendations/${detail.recommendation.id}/decision`, { headers: auth, data: { action: "accepted", fine_print_version: detail.fine_print_version } });
  expect(ok.status()).toBe(200);
  const q1 = await (await request.post("/api/quote", { headers: auth, data: { destination: "US", currency: "USD", ship_to_country: "US", items: [{ sku: "MUG-001" }] } })).json();
  expect(q1.tax_total.amount).toBe("7.60");
  expect(q1.total.amount).toBe("59.60");
  // another key never reaches this merchant's products, and no key at all means the demo shop only
  const other = await (await request.post("/api/merchants", { data: { name: "Other Pots", country: "GB", city: "Stoke" } })).json();
  const denied = await request.post("/api/quote", { headers: { Authorization: `Bearer ${other.api_key}` }, data: { destination: "US", currency: "USD", ship_to_country: "US", items: [{ product_id: mug.id }] } });
  expect(denied.status()).toBe(422);
  expect((await request.get("/api/merchants/me", { headers: { Authorization: "Bearer lf_test_nope" } })).status()).toBe(401);
  // sign out leaves the browser with no store at all (the demo choice made earlier is forgotten too): the console sends the visitor to Connect store
  await page.goto("/connect");
  await page.getByRole("button", { name: /Sign out/ }).click();
  await page.goto("/products");
  await expect(page).toHaveURL(/\/connect\?needs=store/, { timeout: 20_000 });
  await expect(page.getByText(name)).toHaveCount(0);
});

test("K9. a connected merchant syncs its feed from the console: last synced, a plain result, and the publishable key is shown once beside the API key", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/connect");
  const name = `Sync Glassworks ${Date.now() % 100000}`;
  await page.getByLabel("Shop name").fill(name);
  await page.getByLabel("City").fill("Leeds");
  await page.getByRole("button", { name: "Open account" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await page.goto("/keys");  // the keys have their own page
  expect(((await page.locator("#publishable-key").innerText()).trim())).toMatch(/^lf_pub_[0-9a-f]{32}$/);  // safe in a web page; the secret key stays on the server
  await page.goto("/connect");
  await expect(page.getByLabel("Feed address")).toBeVisible();
  await expect(page.getByRole("region", { name: "Feed sync" })).toHaveCount(0);  // nothing to sync until a feed is connected
  await page.getByLabel("Feed address").fill(`${KILN}/products.json`);
  await page.getByRole("button", { name: "Import products" }).click();
  await expect(page.getByText("Imported 9 products.")).toBeVisible({ timeout: 30_000 });
  const box = page.getByRole("region", { name: "Feed sync" });
  await expect(box).toBeVisible();
  await expect(box.getByText(/Last synced .* UTC\./)).toBeVisible();  // the import itself is the first sync
  await box.getByRole("button", { name: "Sync now" }).click();
  await expect(page.locator("#sync-result")).toContainText("Nothing changed since the last sync.", { timeout: 30_000 });
  await expect(page.locator("#last-synced")).toContainText(/Last synced .* UTC/);
  await page.setViewportSize({ width: 390, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: "test-results/connect-sync-phone.png", fullPage: true });
});

test("K10. when the deployment has closed sign-up the console says so in plain words and creates nothing", async ({ page }) => {
  await page.route("**/api/merchants", (route) => (route.request().method() === "POST"
    ? route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "Sign-up is closed on this deployment. The demo merchant is Kiln & Co.; to run your own merchant, run Landfall yourself." }) })
    : route.continue()));
  await page.goto("/connect");
  await page.getByLabel("Shop name").fill("Closed Pots");
  await page.getByLabel("City").fill("Leeds");
  await page.getByRole("button", { name: "Open account" }).click();
  await expect(page.locator(".note-bar.stop")).toContainText("Sign-up is closed on this deployment");
  await expect(page.locator("#api-key")).toHaveCount(0);
});

test("K11. product photos flow through the feed: a merchant imports Kiln's feed, the AI reads the photos once, and the seller sees what it read", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/connect");
  await page.getByLabel("Shop name").fill(`Photo Glassworks ${Date.now() % 100000}`);
  await page.getByLabel("City").fill("Leeds");
  await page.getByRole("button", { name: "Open account" }).click();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("landfall_api_key") ?? "")).not.toBe("");  // the account is opened asynchronously
  const key = await page.evaluate(() => localStorage.getItem("landfall_api_key") ?? "");
  await page.getByLabel("Feed address").fill(`${KILN}/products.json`);
  await page.getByRole("button", { name: "Import products" }).click();
  await expect(page.getByText("Imported 9 products.")).toBeVisible({ timeout: 30_000 });
  const auth = { Authorization: `Bearer ${key}` };
  const cat = await (await request.get("/api/catalogue", { headers: auth })).json();
  const wallet = cat.products.find((p: { sku: string }) => p.sku === "WAL-001");
  expect(wallet.image_urls).toHaveLength(2);  // the feed's photos came with the product
  const rec = await request.post(`/api/products/${wallet.id}/recommend`, { headers: auth, timeout: 120_000 });
  expect(rec.status()).toBe(200);
  const reads = (await rec.json()).recommendation.photo_reads;
  expect(reads).toHaveLength(2);
  expect(reads.every((r: { error: string | null }) => !r.error)).toBe(true);  // both Kiln-hosted photos were fetched, read and dropped
  // the seller sees the photos and what the AI read, in plain words, on the product page
  await page.goto(`/products/${wallet.id}`);
  await expect(page.getByRole("region", { name: "What the AI read in your photos" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("region", { name: "What the AI read in your photos" }).getByText("Photo 2")).toBeVisible();
  await expect(page.getByLabel("Product photos").locator("img")).toHaveCount(2);
  await page.screenshot({ path: "test-results/photo-reads.png", fullPage: true });
});

test("K13. the merchant's own back office: Kiln adds a product with uploaded photos, Landfall syncs it, the AI reads the photos, and the product is processed like any other", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  // the merchant is connected to Landfall by its feed (nine products)
  await page.goto("/connect");
  await page.getByLabel("Shop name").fill(`Sync Pottery ${Date.now() % 100000}`);
  await page.getByLabel("City").fill("Leeds");
  await page.getByRole("button", { name: "Open account" }).click();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("landfall_api_key") ?? "")).not.toBe("");  // the account is opened asynchronously
  const key = await page.evaluate(() => localStorage.getItem("landfall_api_key") ?? "");
  await page.getByLabel("Feed address").fill(`${KILN}/products.json`);
  await page.getByRole("button", { name: "Import products" }).click();
  await expect(page.getByText("Imported 9 products.")).toBeVisible({ timeout: 30_000 });
  // 1. in KILN's back office (not Landfall): add a product with two uploaded photos
  const sku = `JUG-${Date.now() % 100000}`;
  await page.goto(`${KILN}/admin`);
  await expect(page).toHaveURL(/\/login$/);  // the back office needs the staff login
  await page.getByLabel("User name").fill("owner");
  await page.getByLabel("Password").fill(KILN_STAFF_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole("heading", { name: "Connect this shop to Landfall" })).toBeVisible();
  await expect(page.locator("#feed-url")).toContainText("/products.json");
  await page.getByLabel("Title").fill("Stoneware milk jug");
  await page.getByLabel("Description").fill("A stoneware milk jug thrown by hand in our Stoke studio, glazed blue, 400 ml.");
  await page.getByLabel("SKU (optional)").fill(sku);
  for (const [cur, v] of [["GBP", "24.00"], ["USD", "30.00"], ["EUR", "28.00"], ["AUD", "46.00"]] as const) await page.locator(`#price-${cur}`).fill(v);
  const photosDir = path.resolve(__dirname, "../../kiln/public/photos");
  await page.locator("#photos").setInputFiles([path.join(photosDir, "mug-1.jpg"), path.join(photosDir, "mug-2.jpg")]);
  await expect(page.locator("#photo-preview img")).toHaveCount(2);
  await page.getByRole("button", { name: "Add product" }).click();
  await expect(page.locator("#msg")).toContainText("is saved");
  await expect(page.locator(`#plist li[data-sku="${sku}"]`)).toContainText("2 photos");
  // 2. it is in Kiln's shop, with its photo, and in the feed
  await page.goto(KILN);
  await expect(page.locator("#grid .item", { hasText: "Stoneware milk jug" }).locator(".tile.photo a.imglink > img")).toBeVisible();
  const feed = await (await request.get(`${KILN}/products.json`)).json();
  expect(feed.products.find((p: { variants: { sku: string }[] }) => p.variants[0].sku === sku).images).toHaveLength(2);
  // 3. in LANDFALL: Sync now picks it up, recommends it, and the photos are read
  await page.goto("/connect");
  await page.getByRole("button", { name: "Sync now" }).click();
  await expect(page.locator("#sync-result")).toContainText("1 new product was added and recommended", { timeout: 120_000 });
  const cat = await (await request.get("/api/catalogue", { headers: { Authorization: `Bearer ${key}` } })).json();
  const jug = cat.products.find((p: { sku: string }) => p.sku === sku);
  expect(jug.image_urls).toHaveLength(2);
  await page.goto(`/products/${jug.id}`);
  await expect(page.getByRole("region", { name: "What the AI read in your photos" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByLabel("Product photos").locator("img")).toHaveCount(2);
  await page.screenshot({ path: "test-results/k13-synced-product.png", fullPage: true });
  // 4. the merchant edits the description in Kiln: the next sync sends the product back for review; then removes it: it stops being sold
  await page.goto(`${KILN}/admin`);
  await page.locator(`#plist li[data-sku="${sku}"]`).getByRole("button", { name: /^Edit/ }).click();
  await page.getByLabel("Description").fill("A glazed porcelain jug made in a factory in Portugal, 400 ml.");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.locator("#msg")).toContainText("is saved");
  await page.goto("/connect");
  await page.getByRole("button", { name: "Sync now" }).click();
  await expect(page.locator("#sync-result")).toContainText("1 product was changed in your store, so it needs your review again", { timeout: 120_000 });
  await page.goto(`${KILN}/admin`);
  await page.locator(`#plist li[data-sku="${sku}"]`).getByRole("button", { name: /^Remove/ }).click();
  await page.getByRole("button", { name: "Yes, remove" }).click();
  await expect(page.locator(`#plist li[data-sku="${sku}"]`)).toHaveCount(0);
  await page.goto("/connect");
  await page.getByRole("button", { name: "Sync now" }).click();
  await expect(page.locator("#sync-result")).toContainText("1 product left your feed and is no longer sold through the checkout", { timeout: 60_000 });
});

test("G1. Landfall shows nothing until a store is connected: every console page sends a visitor to Connect store, and the demo shop is a deliberate choice", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const route of ["/products", "/passport", "/radar", "/products/p_mug"]) {
    await page.goto(route);
    await expect(page).toHaveURL(/\/connect\?needs=store/, { timeout: 20_000 });
    await expect(page.getByText("Landfall shows nothing until a store is connected")).toBeVisible();
    await expect(page.locator(".shopbox")).toContainText("No store connected");
    const text = await page.locator("body").innerText();
    for (const demoProduct of ["Hand-thrown stoneware mug", "Leather card wallet", "Stoneware serving bowl"]) expect(text, `${demoProduct} must not appear before a store is connected`).not.toContain(demoProduct);
  }
  // the way in is spelled out: where the key comes from and how Kiln is connected
  const how = page.getByRole("region", { name: "How to connect a store" });
  await expect(how).toContainText("shop name, a country and a city");
  await expect(how).toContainText("Shop admin");
  await expect(page.getByRole("button", { name: "Open account" })).toBeVisible();
  // choosing the demo shop on purpose is possible, and it says it is sample data
  await page.getByRole("button", { name: "Open the built-in demo shop" }).click();
  await expect(page.locator(".shopbox")).toContainText("Demo shop (sample data)", { timeout: 20_000 });
  await expect(page.getByText("Ready for duties-included")).toBeVisible({ timeout: 20_000 });
});

test("G2. the Sync now button is on the Products page of a connected store, with the last sync time", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/connect");
  await page.getByLabel("Shop name").fill(`Bar Pottery ${Date.now() % 100000}`);
  await page.getByLabel("City").fill("Leeds");
  await page.getByRole("button", { name: "Open account" }).click();
  await expect(page.getByRole("region", { name: "Product feed sync" })).toHaveCount(0);  // nothing to sync before a feed is connected
  await page.getByLabel("Feed address").fill(`${KILN}/products.json`);
  await page.getByRole("button", { name: "Import products" }).click();
  await expect(page.getByText("Imported 9 products.")).toBeVisible({ timeout: 30_000 });
  await page.goto("/products");
  const bar = page.getByRole("region", { name: "Product feed sync" });
  await expect(bar).toBeVisible({ timeout: 20_000 });
  await expect(bar.getByText(/Last synced .* UTC\./)).toBeVisible();  // the import was the first sync
  await bar.getByRole("button", { name: "Sync now" }).click();
  await expect(page.locator("#sync-result-bar")).toContainText("Nothing changed", { timeout: 60_000 });
  await expect(page.locator("#sync-when")).toContainText(/Last synced .* UTC/);
});

test("K14. Kiln's staff login: the nav offers Staff login, a wrong password is refused, a right one opens the Shop admin (now in the nav), and signing out closes it again", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(KILN);
  await expect(page.getByRole("link", { name: "Shop admin" })).toHaveCount(0);  // shoppers never see the admin
  await page.goto(`${KILN}/admin`);
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get(`${KILN}/api/admin/products`)).status()).toBe(401);
  await page.getByLabel("User name").fill("owner");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("That user name or password is not right.");
  await page.getByLabel("Password").fill(KILN_STAFF_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/admin$/);
  await page.goto(KILN);
  await page.locator("header.top nav").getByRole("link", { name: "Shop admin" }).click();  // a link in the shop's own navigation
  await expect(page.getByRole("heading", { name: "Shop admin" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get(`${KILN}/api/admin/products`)).status()).toBe(401);
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto(`${KILN}/login`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
});

test("K15. a Kiln product page: photos, the price in the chosen country, a plain sentence on what Duties included means, add to cart", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(KILN);
  await expect(page.locator("#grid .item")).toHaveCount(9, { timeout: 20_000 });
  await page.locator("#grid .item", { hasText: "Hand-thrown stoneware mug" }).getByRole("link", { name: "Hand-thrown stoneware mug", exact: true }).first().click();
  await expect(page).toHaveURL(/\/product\?h=mug-001/);
  await expect(page.getByRole("heading", { level: 1, name: "Hand-thrown stoneware mug" })).toBeVisible();
  await expect(page.locator("#product .pics img.big")).toBeVisible();
  await expect(page.locator("#product .thumbrow .thumb")).toHaveCount(2);
  const country = page.locator("#shipto");
  await country.selectOption("US");
  await expect(page.locator("#product .big-price")).toContainText("$38.00");
  await country.selectOption("FR");
  await expect(page.locator("#product .big-price")).toContainText("€");
  await expect(page.locator("#product").getByText("Duties included")).toBeVisible();
  await expect(page.locator("#product").getByText(/nothing is due when the parcel arrives/)).toBeVisible();
  await page.locator("#product").getByRole("button", { name: /Add .* to cart/ }).click();
  await expect(page.locator("#cartcount")).toHaveText("1");
  await page.goto(KILN + "/product?h=nope");
  await expect(page.getByText("We could not find that product")).toBeVisible();
});
