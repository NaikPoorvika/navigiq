import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/**
 * WCAG 2.1 A/AA checks on every main screen. Animations are disabled the way
 * the app disables them for `prefers-reduced-motion`, so colours are measured
 * in their final state rather than mid-fade.
 */
test.use({ reducedMotion: "reduce" });

async function scan(page: Page, name: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    // Leaflet's own tile/attribution markup is third-party and not part of the product's DOM.
    .exclude(".leaflet-container")
    .analyze();
  const problems = results.violations.map((v) => ({
    id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help,
    example: v.nodes[0]?.html?.slice(0, 160),
  }));
  expect(problems, `${name} has accessibility violations: ${JSON.stringify(problems, null, 2)}`).toEqual([]);
}

test("home is accessible", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "What's your mood today?" })).toBeVisible();
  // Scan the loaded page, not skeletons: wait for real cards (a cold API can
  // take a few seconds on its first forecast fetch).
  await expect(page.locator("main article").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await scan(page, "home");
});

test("explore, place and collections are accessible", async ({ page }) => {
  await page.goto("/search?category=park");
  await expect(page.locator("article").first()).toBeVisible({ timeout: 20_000 });
  await scan(page, "search");

  await page.goto("/search?q=lalbagh");
  await page.getByRole("link", { name: /Lalbagh/i }).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForTimeout(1200);
  await scan(page, "place");

  await page.goto("/collections");
  await page.waitForTimeout(1200);
  await scan(page, "collections");
});

test("ask, plans and the builder are accessible", async ({ page }) => {
  await page.goto("/ask");
  await expect(page.getByRole("heading", { name: "Ask NavigIQ" })).toBeVisible();
  await scan(page, "ask");

  await page.goto("/plans");
  await page.waitForTimeout(800);
  await scan(page, "plans");

  await page.goto("/plans/new");
  await page.waitForTimeout(800);
  await scan(page, "plan builder");

  await page.goto("/signin");
  await scan(page, "sign in");
});

test("a built plan is accessible", async ({ page }) => {
  test.slow();
  await page.goto("/plans/new");
  await page.getByRole("button", { name: "Tomorrow", exact: true }).click();
  await page.getByRole("button", { name: "Garden", exact: true }).click();
  await page.getByRole("button", { name: /Build my plan/i }).click();
  await expect(page).toHaveURL(/\/plans\/\d+/, { timeout: 90_000 });
  await page.waitForTimeout(1500);
  await scan(page, "plan");
});

test("keyboard users can reach the main navigation and search", async ({ page, browserName, isMobile }) => {
  // WebKit only moves focus to links when "Full Keyboard Access" is on, and a
  // phone has no Tab key; the behaviour is covered on the other engines.
  test.skip(browserName === "webkit" || Boolean(isMobile), "no tab navigation in this configuration");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "What's your mood today?" })).toBeVisible();
  await page.locator("body").press("Tab");
  await expect(page.getByRole("link", { name: /Skip to content/i })).toBeFocused();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  // Focus continues into the page, not back to the top of the document.
  const tag = await page.evaluate(() => document.activeElement?.tagName ?? "");
  expect(["A", "BUTTON", "INPUT", "TEXTAREA"]).toContain(tag);
});
