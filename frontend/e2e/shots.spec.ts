import { expect, test } from "@playwright/test";

/**
 * Visual capture run (not assertions): `npx playwright test shots --project=chromium`
 * writes full-page screenshots to ../data/artifacts/ui/ for design review.
 */
const OUT = "../data/artifacts/ui";

test.describe.configure({ mode: "serial" });

test("capture screens @capture", async ({ page }) => {
  test.slow();
  const shot = async (name: string) => {
    await page.waitForTimeout(900);
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  };

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "What's your mood today?" })).toBeVisible();
  await page.waitForTimeout(2500);
  await shot("01-home");

  await page.goto("/search?category=lake");
  await expect(page.locator("article").first()).toBeVisible({ timeout: 20_000 });
  await shot("02-search");

  await page.goto("/search?q=lalbagh");
  await page.getByRole("link", { name: /Lalbagh/i }).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForTimeout(1500);
  await shot("03-place");

  await page.goto("/bored?surprise=true");
  await expect(page.getByRole("heading", { level: 3 }).first()).toBeVisible({ timeout: 60_000 });
  await shot("04-bored");

  await page.goto("/ask");
  await page.getByLabel("Message NavigIQ").fill("Plan a 2 day trip with gardens, museums and cafes under 4000 for two");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText(/Open plan/i).first()).toBeVisible({ timeout: 180_000 });
  await shot("05-ask-trip");
  const open = page.getByRole("link", { name: /Open plan/i }).first();
  await open.click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForTimeout(2000);
  await shot("06-plan-trip");

  await page.getByRole("button", { name: /Try a what-if/i }).click();
  await page.getByRole("button", { name: /What if it was more relaxed/i }).click();
  await expect(page.getByText(/If you apply this/i)).toBeVisible({ timeout: 120_000 });
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/07-whatif.png` });
  await page.getByRole("button", { name: /Keep current/i }).click();

  await page.goto("/plans");
  await page.waitForTimeout(1200);
  await shot("08-plans");

  await page.goto("/collections");
  await page.waitForTimeout(1500);
  await shot("09-collections");

  await page.goto("/plans/new");
  await page.waitForTimeout(800);
  await shot("10-plan-new");

  await page.goto("/signin");
  await page.waitForTimeout(600);
  await shot("11-signin");

  // Phone
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.waitForTimeout(2500);
  await shot("12-home-mobile");
  await page.goto("/search?category=cafe");
  await expect(page.locator("article").first()).toBeVisible({ timeout: 20_000 });
  await shot("13-search-mobile");
});
