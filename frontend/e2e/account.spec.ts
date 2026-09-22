import { expect, test } from "@playwright/test";

// The API rate-limits auth endpoints per client (20/min), so these run one at
// a time and on two engines — enough to cover token storage and restore.
test.describe.configure({ mode: "serial" });
test.skip(({ browserName }) => browserName === "firefox", "auth rate limit: covered on chromium and webkit");

/**
 * The account journey against the real API: create an account, save a place,
 * set preferences, and delete the account again (so the run leaves nothing
 * behind in the development database).
 */
test("create an account, save a place, set preferences, delete the account", async ({ page }) => {
  test.slow();
  const email = `e2e_${Date.now().toString(36)}@navigiq.test`;
  const password = "navigiq-e2e-1";

  await page.goto("/signup");
  await page.getByLabel("Name").fill("E2E Tester");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
  await page.waitForLoadState("networkidle");

  // Saving now works without a prompt.
  await page.goto("/search?category=park");
  const card = page.locator("article").first();
  await expect(card).toBeVisible({ timeout: 20_000 });
  const name = (await card.getByRole("link").first().textContent())?.trim() ?? "";
  await card.getByRole("button", { name: /^Save / }).click();
  await expect(page.getByText(`Saved ${name}`)).toBeVisible();

  await page.goto("/saved");
  await expect(page.getByRole("link", { name })).toBeVisible();

  // Preferences round-trip.
  await page.goto("/profile");
  await page.getByRole("button", { name: "Museum", exact: true }).first().click();
  await page.getByRole("button", { name: /Save preferences/ }).click();
  await expect(page.getByText(/Preferences saved/)).toBeVisible({ timeout: 20_000 });
  await page.reload();
  await expect(page.getByRole("button", { name: "Museum", exact: true }).first()).toHaveAttribute("aria-pressed", "true");

  // Signing out hides the account, then the account is removed entirely.
  await page.goto("/profile");
  await page.getByRole("button", { name: /Delete account/ }).click();
  await page.getByLabel(/Confirm with your password/).fill(password);
  await page.getByRole("button", { name: /Delete everything/ }).click();
  await expect(page.getByRole("link", { name: "Sign in" }).first()).toBeVisible({ timeout: 20_000 });
});

test("signing in keeps plans made before signing in", async ({ page }) => {
  test.slow();
  const email = `e2e_claim_${Date.now().toString(36)}@navigiq.test`;
  const password = "navigiq-e2e-1";

  // Anonymous plan first.
  await page.goto("/plans/new");
  await page.getByRole("button", { name: "Tomorrow", exact: true }).click();
  await page.getByRole("button", { name: "Park", exact: true }).click();
  await page.getByRole("button", { name: /Build my plan/i }).click();
  await expect(page).toHaveURL(/\/plans\/\d+/, { timeout: 90_000 });
  const title = await page.getByRole("heading", { level: 1 }).textContent();

  await page.goto("/signup");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 30_000 });
  await page.waitForLoadState("networkidle");

  await page.goto("/plans");
  await expect(page.getByText(title!.trim())).toBeVisible({ timeout: 20_000 });

  await page.goto("/profile");
  await page.getByRole("button", { name: /Delete account/ }).click();
  await page.getByLabel(/Confirm with your password/).fill(password);
  await page.getByRole("button", { name: /Delete everything/ }).click();
  await expect(page.getByRole("link", { name: "Sign in" }).first()).toBeVisible({ timeout: 20_000 });
});
