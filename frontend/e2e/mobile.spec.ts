import { devices, expect, test } from "@playwright/test";

/** Phone-specific behaviour: tab bar, bottom sheets, and the map/timeline switch. */
test.use({ ...devices["Pixel 7"] });

test("the tab bar is the main navigation on a phone", async ({ page }) => {
  await page.goto("/");
  const nav = page.locator("nav[aria-label='Main']").last();
  await expect(nav).toBeVisible();
  await nav.getByRole("link", { name: "Plans" }).click();
  await expect(page).toHaveURL(/\/plans$/);
  await nav.getByRole("link", { name: "Ask" }).click();
  await expect(page.getByRole("heading", { name: "Ask NavigIQ" })).toBeVisible();
  // Tap targets are comfortable.
  const box = await nav.getByRole("link", { name: "Explore" }).boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(44);
});

test("filters open in a bottom sheet and apply", async ({ page }) => {
  await page.goto("/search");
  await page.getByRole("button", { name: /^Filters/ }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet).toBeVisible();
  await sheet.getByRole("button", { name: "Lake", exact: true }).click();
  await sheet.getByRole("button", { name: /^Show / }).click();
  await expect(page).toHaveURL(/category=.*lake/);
  await expect(page.getByRole("button", { name: /Remove Lake filter/ })).toBeVisible();
  await expect(page.locator("article").first()).toBeVisible({ timeout: 20_000 });
});

test("a plan switches between timeline and map", async ({ page }) => {
  test.slow();
  await page.goto("/plans/new");
  await page.getByRole("button", { name: "Tomorrow", exact: true }).click();
  await page.getByRole("button", { name: "Garden", exact: true }).click();
  await page.getByRole("button", { name: /Build my plan/i }).click();
  await expect(page).toHaveURL(/\/plans\/\d+/, { timeout: 90_000 });

  await expect(page.locator("li[id^='stop-']").first()).toBeVisible();
  await page.getByRole("radio", { name: "Map" }).click();
  await expect(page.getByRole("region", { name: /Map of/ })).toBeVisible();
  await page.getByRole("radio", { name: "Timeline" }).click();
  await expect(page.locator("li[id^='stop-']").first()).toBeVisible();
});

test("results can be shown on a map from a chat answer", async ({ page }) => {
  test.slow();
  await page.goto("/ask?q=parks%20near%20Jayanagar&new=true");
  await expect(page.getByRole("button", { name: /On the map/i })).toBeVisible({ timeout: 120_000 });
  await page.getByRole("button", { name: /On the map/i }).click();
  await expect(page.getByRole("dialog").getByRole("region", { name: /Map of the places/ })).toBeVisible();
});
