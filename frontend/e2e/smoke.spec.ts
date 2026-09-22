import { expect, test, type Page } from "@playwright/test";

/** Critical journeys against the real API. Nothing here is mocked. */

async function gotoHome(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "What's your mood today?" })).toBeVisible();
}

test("home shows real context, recommendations and collections", async ({ page }) => {
  await gotoHome(page);
  // The context line comes from the server's IST clock.
  await expect(page.getByText(/in Bengaluru/i).first()).toBeVisible();
  const rightNow = page.getByRole("region", { name: /Right now|Good for|Indoor ideas/i }).first();
  await expect(rightNow).toBeVisible({ timeout: 20_000 });
  // Real places, with a reason from the ranking engine.
  const firstCard = page.locator("article").first();
  await expect(firstCard).toBeVisible();
  await expect(page.getByRole("link", { name: /All collections/i })).toBeVisible();
});

test("explore search finds places and opens a place page", async ({ page }) => {
  await page.goto("/search?q=lalbagh");
  const link = page.getByRole("link", { name: /Lalbagh/i }).first();
  await expect(link).toBeVisible({ timeout: 20_000 });
  await link.click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Lalbagh/i);
  // Honest facts only: an estimate label, not a rating.
  await expect(page.getByText(/NavigIQ estimate/i)).toBeVisible();
  await expect(page.getByText(/star rating/i)).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Open in OpenStreetMap/i })).toBeVisible();
});

test("filters narrow the catalogue and can be cleared", async ({ page }) => {
  await page.goto("/search?category=museum");
  await expect(page.getByText(/^\d+ places?/)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("button", { name: /Remove Museum filter/i })).toBeVisible();
  await page.getByRole("button", { name: /Clear all/i }).click();
  await expect(page).toHaveURL(/\/search$/);
});

test("the planner builds a validated plan and can change one stop", async ({ page }) => {
  test.slow();
  await page.goto("/plans/new");
  await page.getByRole("button", { name: "Tomorrow", exact: true }).click();
  await page.getByRole("button", { name: "Full day", exact: true }).click();
  await page.getByRole("button", { name: "Garden", exact: true }).click();
  await page.getByRole("button", { name: "Museum", exact: true }).click();
  await page.getByRole("button", { name: /Build my plan/i }).click();

  await expect(page).toHaveURL(/\/plans\/\d+/, { timeout: 90_000 });
  await expect(page.getByText("Checked", { exact: true })).toBeVisible();
  await expect(page.getByText(/Transition buffers are included/i)).toBeVisible();
  await expect(page.getByText(/travel/i).first()).toBeVisible();

  const stops = page.locator("li[id^='stop-']");
  await expect(stops.first()).toBeVisible();
  const before = await stops.count();
  expect(before).toBeGreaterThan(1);

  // Remove the first stop through the stop menu.
  await stops.first().getByRole("button", { name: /^Change stop/ }).click();
  await page.getByRole("menuitem", { name: /Remove from plan/i }).click();
  await expect(page.getByText("Plan updated")).toBeVisible({ timeout: 90_000 });
  await expect(page.locator("li[id^='stop-']")).toHaveCount(before - 1);
  // The change can be undone.
  await expect(page.getByRole("button", { name: /Undo/i })).toBeVisible();
});

test("ask answers a question with sources and never invents them", async ({ page }) => {
  test.slow();
  await page.goto("/ask");
  await expect(page.getByRole("heading", { name: "Ask NavigIQ" })).toBeVisible();
  await page.getByLabel("Message NavigIQ").fill("Why is Lalbagh famous?");
  await page.getByRole("button", { name: "Send message" }).click();
  const sources = page.getByText("Sources", { exact: true });
  await expect(sources).toBeVisible({ timeout: 120_000 });
  const links = page.locator("ol li a[target='_blank']");
  await expect(links.first()).toBeVisible();
  for (const href of await links.evaluateAll((els) => els.map((e) => (e as HTMLAnchorElement).href))) {
    expect(href).toMatch(/^https?:\/\/(en\.wikipedia\.org|www\.wikidata\.org|www\.openstreetmap\.org|open-meteo\.com)/);
  }
});

test("I'm bored gives one idea at a time and can swap it", async ({ page }) => {
  test.slow();
  await page.goto("/bored");
  await page.getByRole("button", { name: /^Surprise me/ }).click();
  const heading = page.getByRole("heading", { level: 3 }).first();
  await expect(heading).toBeVisible({ timeout: 60_000 });
  const first = await heading.textContent();
  await page.getByRole("button", { name: /Show me something different/i }).click();
  await expect
    .poll(async () => (await page.getByRole("heading", { level: 3 }).first().textContent()) ?? "", { timeout: 60_000 })
    .not.toBe(first);
});

test("saving a place asks for an account when signed out", async ({ page }) => {
  await page.goto("/search?category=park");
  await expect(page.locator("article").first()).toBeVisible({ timeout: 20_000 });
  await page.locator("article").first().getByRole("button", { name: /^Save / }).click();
  await expect(page.getByText(/Sign in to save places/i)).toBeVisible();
});

test("an unknown route shows the not-found screen", async ({ page }) => {
  await page.goto("/definitely-not-a-page");
  await expect(page.getByRole("heading", { name: /wandered off/i })).toBeVisible();
});
