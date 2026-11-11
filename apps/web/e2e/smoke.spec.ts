import AxeBuilder from "@axe-core/playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

// All nine screens at phone and desktop width: content present, no serious axe violations, screenshots saved.
const SCREENS: { name: string; path: string; expect: RegExp }[] = [
  { name: "how-it-works", path: "/", expect: /No surprise bills at the door/ },
  { name: "products", path: "/products", expect: /review the AI.s recommendation and accept it/ },
  { name: "product", path: "/products/p_mug", expect: /AI recommendation/ },
  { name: "questions", path: "/products/p_wallet/questions", expect: /Made in China|quick check/i },
  { name: "passport", path: "/passport", expect: /Your seller passport/ },
  { name: "radar", path: "/radar", expect: /Rule Radar/ },
  { name: "time-machine", path: "/time-machine", expect: /TARIFF TIME MACHINE/ },
  { name: "shop", path: "/shop", expect: /Your cart/ },
  { name: "checkout", path: "/checkout?items=p_mug:1&ship=US", expect: /Order summary/ },
  { name: "ops", path: "/ops", expect: /Landfall Ops/ },
];
const SIZES = [
  { tag: "phone", width: 390, height: 844 },
  { tag: "desktop", width: 1440, height: 900 },
];

async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(700); // mock latency
}

for (const size of SIZES) {
  for (const s of SCREENS) {
    test(`${s.name} @ ${size.tag}`, async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(s.path);
      await expect(page.getByText(s.expect).first()).toBeVisible({ timeout: 15_000 });
      await settle(page);
      await page.screenshot({ path: `test-results/screens/${s.name}-${size.tag}.png`, fullPage: true });
      const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa"]).analyze();
      const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => `${v.id}: ${v.nodes.slice(0, 2).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, "no horizontal page scroll").toBeLessThanOrEqual(1);
      expect(errors).toEqual([]);
    });
  }
}

test("journey: bulk accept takes only High-band products; a question changes the price", async ({ page, request }) => {
  // Real recommender, real data: two clear listings are added through the API and recommended by Haiku.
  const stamp = Date.now();
  const clear = [
    { title: `Men's cotton t-shirt ${stamp}`, description: "Men's knitted 100% cotton crew neck t-shirt, sewn in our Leicester workshop." },
    { title: `Leather bifold wallet ${stamp}`, description: "Full grain leather bifold wallet with eight card slots, handmade in Walsall." },
  ];
  for (const c of clear) {
    const made = await request.post("/api/products", { data: { ...c, prices: { GBP: "30.00", USD: "38.00", EUR: "35.00" }, category: "cotton" } });
    expect(made.ok()).toBeTruthy();
    const { id } = await made.json();
    expect((await request.post(`/api/products/${id}/recommend`)).ok()).toBeTruthy();
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/products");
  await expect(page.getByText("Stoneware serving bowl", { exact: true })).toBeVisible();
  // Only a not-yet-reviewed High-band product with no open question can be selected; everything else is disabled, whatever today's recommender said.
  const products = (await (await request.get("/api/catalogue")).json()).products as { title: string; band: string; review_status: string; question_count: number }[];
  const isSelectable = (p: { band: string; review_status: string; question_count: number }) => p.review_status === "not_reviewed" && p.band === "high" && p.question_count === 0;
  for (const p of products) {
    const box = page.getByLabel(p.title, { exact: false }).first();
    if (isSelectable(p)) await expect(box).toBeEnabled();
    else await expect(box).toBeDisabled();
  }
  const highOpen = products.filter(isSelectable).length;
  const selectAll = page.getByLabel("Select all High-confidence products");
  if (highOpen === 0) {
    // Real recommender, real data: on the wider closed list a clear listing often still draws a price-relevant question, so a High-band
    // product is not guaranteed today. The behaviour to prove then is the other half of the rule: nothing outside High can be bulk accepted.
    test.info().annotations.push({ type: "note", description: "no High-band product today; asserting that bulk accept is unavailable" });
    await expect(selectAll).toBeDisabled();
    await expect(page.getByRole("button", { name: /^Accept selected$/ })).toBeDisabled();
  } else {
    await selectAll.check();
    await page.getByRole("button", { name: new RegExp(`Accept ${highOpen} recommendation`) }).click();
    await expect(page.getByText(new RegExp(`Accepted ${highOpen}\.`))).toBeVisible();
  }
  await page.goto("/products/p_wallet/questions");
  await page.getByRole("radio", { name: /United Kingdom/ }).first().click();
  await expect(page.getByText(/US buyer duty and tax/)).toBeVisible();
});

test("checkout shows duty as its own line and total 59.60", async ({ page }) => {
  await page.goto("/checkout?items=p_mug:1&ship=US");
  await expect(page.getByText("Import duties and taxes, included")).toBeVisible();
  await expect(page.getByText("$59.60 USD")).toBeVisible();
});

test("time machine runs on the real register: demo anchor and share image", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/time-machine?product=p_mug&origin=GB&destination=US&date=2026-10-29");
  await expect(page.getByText("$59.60").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/In January 2025/)).toBeVisible();
  await expect(page.getByText("$52.00").first()).toBeVisible();
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", /timemachine\/share\.png\?product=p_mug/);
  const res = await request.get("/api/timemachine/share.png?product=p_mug&origin=GB&destination=US&date=2026-10-29");
  expect(res.status()).toBe(200);
  expect(res.headers()["content-type"]).toBe("image/png");
  const body = await res.body();
  expect([...body.subarray(0, 4)]).toEqual([0x89, 0x50, 0x4e, 0x47]);
  mkdirSync("test-results/screens", { recursive: true });
  writeFileSync("test-results/screens/share-time-machine.png", body);
  expect(body.length).toBeGreaterThan(20_000);
});
