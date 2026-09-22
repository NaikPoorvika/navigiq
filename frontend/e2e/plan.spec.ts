import { expect, test, type Page } from "@playwright/test";

/**
 * NQ-026 definition of done:
 *  - fill the form, submit -> at least 3 markers on a map and a visible timeline
 *  - OpenStreetMap attribution is visible
 *  - an impossible request shows clickable fixes, not a blank screen
 *  - backend error codes each get their own screen
 */

/** Tomorrow as YYYY-MM-DD, so the test never plans a time that has passed. */
function tomorrow(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function startFrom(page: Page, place: string) {
  await page.goto("/#/plan");
  await page.locator("#origin").fill(place);
  const firstOption = page.locator(".place-options button").first();
  await expect(firstOption).toBeVisible();
  await firstOption.click();
  await expect(page.locator(".picked")).toBeVisible();
  await page.locator("#date").fill(tomorrow());
}

async function pick(page: Page, category: string) {
  await page.getByRole("button", { name: category, exact: true }).click();
}

test("a real plan shows at least 3 numbered stops on a map and a timeline", async ({ page }) => {
  await startFrom(page, "Koramangala");
  await page.locator("#start").fill("15:00");
  await page.locator("#end").fill("20:00");
  await pick(page, "Cafe");
  await pick(page, "Park");
  await pick(page, "Restaurant");
  await page.getByRole("button", { name: /plan my trip/i }).click();

  // Staged progress, not a bare spinner.
  await expect(page.getByText("Planning your trip")).toBeVisible();

  const markers = page.locator(".map-pin.stop");
  await expect(markers.first()).toBeVisible({ timeout: 60_000 });
  expect(await markers.count()).toBeGreaterThanOrEqual(3);

  // Every marker has a matching timeline stop.
  await expect(page.locator(".tl-stop")).toHaveCount(await markers.count());

  // Licence requirement.
  await expect(page.locator(".leaflet-control-attribution")).toContainText("OpenStreetMap");

  // Costs are presented as estimates.
  await expect(page.getByText(/estimated/i).first()).toBeVisible();
});

test("an impossible request offers clickable fixes", async ({ page }) => {
  await startFrom(page, "Koramangala");
  await page.locator("#start").fill("15:00");
  await page.locator("#end").fill("16:00");
  await pick(page, "Museum");
  await page.getByLabel("Priority").selectOption("must");
  await page.getByLabel("How many").selectOption("3");
  await page.getByRole("button", { name: /plan my trip/i }).click();

  await expect(page.getByText("This trip doesn't quite fit")).toBeVisible({ timeout: 60_000 });
  const fixes = page.locator(".relax");
  expect(await fixes.count()).toBeGreaterThan(0);
});

/** Error screens: the backend's replies are faked so each code is certain. */
const ERRORS: [string, number, string][] = [
  ["ROUTING_UNAVAILABLE", 503, "Travel times are unavailable right now"],
  ["NO_CANDIDATES", 404, "Nothing matched near your starting point"],
  ["VALIDATION_FAILED", 500, "This plan didn't pass our checks"],
];

for (const [code, status, heading] of ERRORS) {
  test(`${code} has its own screen`, async ({ page }) => {
    await page.route("**/api/v1/plan", (route) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify({ detail: { error: { code, message: "test", details: null } } }),
      }),
    );
    await startFrom(page, "Koramangala");
    await pick(page, "Park");
    await page.getByRole("button", { name: /plan my trip/i }).click();
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    await expect(page.getByText(`Code: ${code}`)).toBeVisible();
  });
}

test("an unreachable backend says so instead of failing silently", async ({ page }) => {
  await page.route("**/api/v1/plan", (route) => route.abort("connectionrefused"));
  await startFrom(page, "Koramangala");
  await pick(page, "Park");
  await page.getByRole("button", { name: /plan my trip/i }).click();
  await expect(page.getByRole("heading", { name: "Can't reach NavigIQ" })).toBeVisible();
});