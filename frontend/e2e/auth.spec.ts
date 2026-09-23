import { expect, test } from "@playwright/test";

/**
 * Real accounts, end to end against the real backend: sign up, fill the
 * profile, sign out, sign back in - and the profile is still there, because
 * it lives on the server now, not in the browser.
 */

const password = "planning123";
const email = () => `e2e${Date.now()}${Math.floor(Math.random() * 1000)}@e2e.navigiq.local`;

test("sign up, sign out, sign back in - the profile survives", async ({ page }) => {
  const address = email();

  // Step 1 - account (created on the server here)
  await page.goto("/#/welcome");
  await page.locator("#email").fill(address);
  await page.locator("#pw").fill(password);
  await page.locator("#confirm").fill(password);
  await page.getByRole("button", { name: /create account/i }).click();

  // Step 2 - about you
  await expect(page.getByRole("heading", { name: /about yourself/i })).toBeVisible();
  await page.locator("#name").fill("Test Traveller");
  await page.locator("#origin").fill("Koramangala");
  await page.locator(".place-options button").first().click();
  await page.getByRole("button", { name: /continue/i }).click();

  // Step 3 - preferences
  await page.getByRole("button", { name: /^Park/ }).click();
  await page.getByRole("button", { name: /^Vegetarian/ }).click();
  await page.getByRole("button", { name: /finish/i }).click();
  await expect(page.getByRole("heading", { name: /all set, test/i })).toBeVisible();

  // Sign out
  await page.goto("/#/profile");
  await page.getByRole("button", { name: /sign out/i }).click();
  await expect(page.getByRole("link", { name: /sign in/i })).toBeVisible();

  // Sign back in - with different capitalisation, which must still work
  await page.goto("/#/signin");
  await page.locator("#si-email").fill(address.toUpperCase());
  await page.locator("#si-pw").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  // Sign-in is asynchronous - wait until the header shows the account.
  await expect(page.locator(".avatar-link")).toBeVisible();

  // The profile came back from the server
  await page.goto("/#/profile");
  await expect(page.locator("#pname")).toHaveValue("Test Traveller");
  await expect(page.locator(".picked")).toContainText("Koramangala");
  await expect(page.getByLabel(/vegetarian food only/i)).toBeChecked();
});

test("a wrong password is refused with a clear message", async ({ page }) => {
  await page.goto("/#/signin");
  await page.locator("#si-email").fill("nobody@e2e.navigiq.local");
  await page.locator("#si-pw").fill("wrongpass1");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("alert")).toContainText("don't match");
});

test("signing up twice with the same email is refused", async ({ page }) => {
  const address = email();
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.goto("/#/profile");
    const signOut = page.getByRole("button", { name: /sign out/i });
    if (await signOut.isVisible().catch(() => false)) await signOut.click();

    await page.goto("/#/welcome");
    await page.locator("#email").fill(address);
    await page.locator("#pw").fill(password);
    await page.locator("#confirm").fill(password);
    await page.getByRole("button", { name: /create account/i }).click();
    if (attempt === 0) await expect(page.getByRole("heading", { name: /about yourself/i })).toBeVisible();
  }
  await expect(page.getByText(/already exists/i)).toBeVisible();
});

test("deleting the account needs the password, and then it's gone", async ({ page }) => {
  const address = email();
  await page.goto("/#/welcome");
  await page.locator("#email").fill(address);
  await page.locator("#pw").fill(password);
  await page.locator("#confirm").fill(password);
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page.getByRole("heading", { name: /about yourself/i })).toBeVisible();

  await page.goto("/#/profile");
  await page.getByRole("button", { name: /delete my account/i }).click();

  // Wrong password: refused, account kept.
  await page.locator("#del-pw").fill("wrongpass1");
  await page.getByRole("button", { name: /delete permanently/i }).click();
  await expect(page.getByRole("alert")).toContainText("isn't right");
  // Right password: deleted and signed out.
  await page.locator("#del-pw").fill(password);
  await page.getByRole("button", { name: /delete permanently/i }).click();
  // The account is gone when the header stops showing it. "Sign in" appears
  // in more than one place on the home page, so check the avatar instead.
  await expect(page.locator(".avatar-link")).toHaveCount(0);
  await expect(page.locator(".account")).toContainText("Sign in");

  // The account really is gone.
  await page.goto("/#/signin");
  await page.locator("#si-email").fill(address);
  await page.locator("#si-pw").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("alert")).toContainText("don't match");
});
