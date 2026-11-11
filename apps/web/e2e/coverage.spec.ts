import { expect, test } from "@playwright/test";

const KILN = `http://127.0.0.1:${process.env.E2E_KILN_PORT ?? 3410}`;
const overflow = (page: import("@playwright/test").Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test("C1. Coverage and sources (desktop): a table of covered origins by covered destinations, a table of sources, and a disclaimer; nothing that is not covered is listed", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/products");
  await page.getByRole("link", { name: "Coverage and sources" }).click();  // the console nav links to it
  await expect(page.getByRole("heading", { name: "Coverage and sources" })).toBeVisible({ timeout: 20_000 });
  const matrix = page.getByRole("region", { name: "Covered countries" });
  for (const dest of ["United States", "United Kingdom", "European Union (27 states)", "Australia"]) await expect(matrix.getByRole("columnheader", { name: dest })).toBeVisible();
  await expect(matrix.locator("tbody tr")).toHaveCount(12);  // the twelve covered origins
  await expect(matrix.locator('tr[data-origin="VN"]').getByRole("img", { name: /Vietnam to United States: covered/ })).toBeVisible();
  await expect(matrix.locator('tr[data-origin="CN"] td .badge')).toHaveCount(4);  // covered for all four destinations
  await expect(page.getByText(/hand-curated table, to be confirmed by a customs broker/)).toBeVisible();  // Australia's footnote
  const src = page.getByRole("region", { name: "Rate sources" });
  for (const id of ["usitc", "uk", "tedb", "federal_register", "au_table"]) await expect(src.locator(`tr[data-source="${id}"]`)).toBeVisible();
  await expect(src.locator('tr[data-source="usitc"]')).toContainText("Every night, 02:00 UTC");
  await expect(src.locator('tr[data-source="federal_register"]')).toContainText(/person approves/);
  await expect(src.locator('tr[data-source="au_table"]')).toContainText("not refreshed automatically");
  await expect(page.getByText(/48 hours/).first()).toBeVisible();
  await expect(page.getByRole("note")).toContainText("planned for a later phase");
  const main = await page.locator("main").innerText();
  for (const absent of ["Canada", "Mexico", "TARIC", "Section 232", "Not built", "not built"]) expect(main, `${absent} is not covered, so it is not listed`).not.toContain(absent);
});

test("C2. Coverage and sources at phone width: no sideways scroll of the page (the tables scroll inside their own frame)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/coverage");
  await expect(page.getByRole("heading", { name: "Coverage and sources" })).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('tr[data-origin="GB"]')).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: "test-results/coverage-phone.png", fullPage: true });
});

test("C3. Kiln's footer links to Coverage and sources", async ({ page }) => {
  await page.goto(KILN);
  const link = page.getByRole("link", { name: "Coverage and sources" });
  await expect(link).toHaveAttribute("href", /\/coverage$/, { timeout: 20_000 });
});
