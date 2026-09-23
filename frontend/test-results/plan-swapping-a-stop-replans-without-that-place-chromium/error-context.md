# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: plan.spec.ts >> swapping a stop replans without that place
- Location: e2e\plan.spec.ts:105:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByText(/1 place skipped/i)
Expected: visible
Timeout: 60000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByText(/1 place skipped/i) with timeout 60000ms
  - waiting for getByText(/1 place skipped/i)

```

```yaml
- banner:
  - link "NavigIQ":
    - /url: "#/"
  - navigation "Main":
    - link "Home":
      - /url: "#/"
    - link "Plan a trip":
      - /url: "#/plan"
    - link "Your plans":
      - /url: "#/plans"
    - link "Plan with AI":
      - /url: "#/discover"
  - link "Sign in":
    - /url: "#/signin"
  - link "Get started":
    - /url: "#/welcome"
- main:
  - heading "Plan a trip" [level=1]
  - text: Real places from OpenStreetMap Travel times from road data Opening hours checked where known Every plan verified before you see it Where and when Starting from
  - textbox "Starting from":
    - /placeholder: Koramangala, Cubbon Park, MG Road…
    - text: Koramangala
  - text: Koramangala Date
  - textbox "Date": 2026-09-24
  - text: From
  - textbox "From": 15:00
  - text: Until
  - textbox "Until": 20:00
  - text: What you'd like to do
  - button "Cafe" [pressed]
  - button "Restaurant"
  - button "Street Food"
  - button "Bar"
  - button "Dessert"
  - button "Historical Site"
  - button "Temple"
  - button "Museum"
  - button "Art Gallery"
  - button "Park" [pressed]
  - button "Lake"
  - button "Viewpoint"
  - button "Sunset Spot"
  - button "Nature"
  - button "Shopping"
  - button "Market"
  - button "Bookstore"
  - button "Nightlife"
  - button "Entertainment"
  - button "Landmark"
  - list:
    - listitem:
      - text: Cafe
      - combobox "Priority":
        - option "Must"
        - option "Prefer" [selected]
        - option "If it fits"
      - combobox "How many":
        - option "× 1" [selected]
        - option "× 2"
        - option "× 3"
    - listitem:
      - text: Park
      - combobox "Priority":
        - option "Must"
        - option "Prefer" [selected]
        - option "If it fits"
      - combobox "How many":
        - option "× 1" [selected]
        - option "× 2"
        - option "× 3"
  - checkbox "Vegetarian food only"
  - text: Vegetarian food only How you'll get around
  - button "Walking" [pressed]
  - button "Auto" [pressed]
  - button "Cab"
  - button "Own car"
  - button "Bike"
  - text: Pace
  - button "Quick"
  - button "Balanced" [pressed]
  - button "Relaxed"
  - text: Budget ₹
  - spinbutton "Budget ₹"
  - text: People
  - spinbutton "People": "1"
  - text: Walk (km)
  - spinbutton "Walk (km)": "2"
  - button "Plan my trip"
  - text: Your plan · Thursday, 24 Sept
  - heading "2 stops from Koramangala" [level=2]
  - link "Open route in Google Maps":
    - /url: https://www.google.com/maps/dir/?api=1&origin=Koramangala%2C+Bengaluru&destination=Akhila+Park%2C+Bengaluru&travelmode=walking&waypoints=Dialogues+Cafe%2C+Bengaluru
  - text: Google labels stops with its own nearest address — same places. 15:03–16:53 · 1 h 53 min ≈ ₹300 estimated 694 m walking Light rain · 23°C
  - img
  - button
  - button "1"
  - button "2"
  - button "Zoom in"
  - button "Zoom out"
  - link "Leaflet":
    - /url: https://leafletjs.com
  - text: ©
  - link "OpenStreetMap":
    - /url: https://www.openstreetmap.org/copyright
  - text: contributors
  - paragraph: Routes follow real roads, from OpenStreetMap data.
  - list:
    - listitem:
      - strong: Start
      - text: · Koramangala 15:00
    - listitem: 3 min walk
    - listitem:
      - text: 1 Cafe ≈ ₹300 typical
      - link "Dialogues Cafe":
        - /url: "#/place/32813"
      - text: 15:03–15:48 45 min here
      - link "On Google Maps":
        - /url: https://www.google.com/maps/search/?api=1&query=Dialogues+Cafe%2C+Bengaluru
      - button "Swap"
      - button "Remove"
      - strong: Replace Dialogues Cafe
      - button "Close"
      - button "Let NavigIQ choose Picks the best fit for your time and route":
        - strong: Let NavigIQ choose
        - text: Picks the best fit for your time and route
      - button "The Hole In The Wall Cafe 87 m from this stop":
        - strong: The Hole In The Wall Cafe
        - text: 87 m from this stop
      - button "Starbucks 1.2 km from this stop":
        - strong: Starbucks
        - text: 1.2 km from this stop
      - button "Fast Coffee 35 m from this stop":
        - strong: Fast Coffee
        - text: 35 m from this stop
      - button "Daily Bakehouse 466 m from this stop":
        - strong: Daily Bakehouse
        - text: 466 m from this stop
      - button "Pahala Rasagola shop 651 m from this stop":
        - strong: Pahala Rasagola shop
        - text: 651 m from this stop
      - button "Sour House 788 m from this stop":
        - strong: Sour House
        - text: 788 m from this stop
      - paragraph: A replacement is planned into your day — if it can't fit the times, you'll be told.
    - listitem: 5 min walk
    - listitem:
      - text: 2 Park Free
      - link "Akhila Park":
        - /url: "#/place/40145"
      - text: 15:53–16:53 60 min here Hours unverified
      - link "On Google Maps":
        - /url: https://www.google.com/maps/search/?api=1&query=Akhila+Park%2C+Bengaluru
      - button "Swap"
      - button "Remove"
    - listitem:
      - strong: Done
      - text: 16:53
  - paragraph: Food and entry costs are typical estimates for each category, not the venue's actual prices. Transport fares are estimated from published rates. Travel times are estimates from road data and time of day, not live traffic. Map data © OpenStreetMap contributors.
- contentinfo:
  - text: "Map and place data © OpenStreetMap contributors, ODbL · Weather: Open-Meteo · Photos: Wikimedia Commons contributors ·"
  - link "Credits":
    - /url: "#/credits"
```

# Test source

```ts
  19  |   await page.goto("/#/plan");
  20  |   await page.locator("#origin").fill(place);
  21  |   const firstOption = page.locator(".place-options button").first();
  22  |   await expect(firstOption).toBeVisible();
  23  |   await firstOption.click();
  24  |   await expect(page.locator(".picked")).toBeVisible();
  25  |   await page.locator("#date").fill(tomorrow());
  26  | }
  27  | 
  28  | async function pick(page: Page, category: string) {
  29  |   await page.getByRole("button", { name: category, exact: true }).click();
  30  | }
  31  | 
  32  | test("a real plan shows at least 3 numbered stops on a map and a timeline", async ({ page }) => {
  33  |   await startFrom(page, "Koramangala");
  34  |   await page.locator("#start").fill("15:00");
  35  |   await page.locator("#end").fill("20:00");
  36  |   await pick(page, "Cafe");
  37  |   await pick(page, "Park");
  38  |   await pick(page, "Restaurant");
  39  |   await page.getByRole("button", { name: /plan my trip/i }).click();
  40  | 
  41  |   // Staged progress, not a bare spinner.
  42  |   await expect(page.getByText("Planning your trip")).toBeVisible();
  43  | 
  44  |   const markers = page.locator(".map-pin.stop");
  45  |   await expect(markers.first()).toBeVisible({ timeout: 60_000 });
  46  |   expect(await markers.count()).toBeGreaterThanOrEqual(3);
  47  | 
  48  |   // Every marker has a matching timeline stop.
  49  |   await expect(page.locator(".tl-stop")).toHaveCount(await markers.count());
  50  | 
  51  |   // Licence requirement.
  52  |   await expect(page.locator(".leaflet-control-attribution")).toContainText("OpenStreetMap");
  53  | 
  54  |   // Costs are presented as estimates.
  55  |   await expect(page.getByText(/estimated/i).first()).toBeVisible();
  56  | });
  57  | 
  58  | test("an impossible request offers clickable fixes", async ({ page }) => {
  59  |   await startFrom(page, "Koramangala");
  60  |   await page.locator("#start").fill("15:00");
  61  |   await page.locator("#end").fill("16:00");
  62  |   await pick(page, "Museum");
  63  |   await page.getByLabel("Priority").selectOption("must");
  64  |   await page.getByLabel("How many").selectOption("3");
  65  |   await page.getByRole("button", { name: /plan my trip/i }).click();
  66  | 
  67  |   await expect(page.getByText("This trip doesn't quite fit")).toBeVisible({ timeout: 60_000 });
  68  |   const fixes = page.locator(".relax");
  69  |   expect(await fixes.count()).toBeGreaterThan(0);
  70  | });
  71  | 
  72  | /** Error screens: the backend's replies are faked so each code is certain. */
  73  | const ERRORS: [string, number, string][] = [
  74  |   ["ROUTING_UNAVAILABLE", 503, "Travel times are unavailable right now"],
  75  |   ["NO_CANDIDATES", 404, "Nothing matched near your starting point"],
  76  |   ["VALIDATION_FAILED", 500, "This plan didn't pass our checks"],
  77  | ];
  78  | 
  79  | for (const [code, status, heading] of ERRORS) {
  80  |   test(`${code} has its own screen`, async ({ page }) => {
  81  |     await page.route("**/api/v1/plan", (route) =>
  82  |       route.fulfill({
  83  |         status,
  84  |         contentType: "application/json",
  85  |         body: JSON.stringify({ detail: { error: { code, message: "test", details: null } } }),
  86  |       }),
  87  |     );
  88  |     await startFrom(page, "Koramangala");
  89  |     await pick(page, "Park");
  90  |     await page.getByRole("button", { name: /plan my trip/i }).click();
  91  |     await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  92  |     await expect(page.getByText(`Code: ${code}`)).toBeVisible();
  93  |   });
  94  | }
  95  | 
  96  | test("an unreachable backend says so instead of failing silently", async ({ page }) => {
  97  |   await page.route("**/api/v1/plan", (route) => route.abort("connectionrefused"));
  98  |   await startFrom(page, "Koramangala");
  99  |   await pick(page, "Park");
  100 |   await page.getByRole("button", { name: /plan my trip/i }).click();
  101 |   await expect(page.getByRole("heading", { name: "Can't reach NavigIQ" })).toBeVisible();
  102 | });
  103 | 
  104 | 
  105 | test("swapping a stop replans without that place", async ({ page }) => {
  106 |   await startFrom(page, "Koramangala");
  107 |   await page.locator("#start").fill("15:00");
  108 |   await page.locator("#end").fill("20:00");
  109 |   await pick(page, "Cafe");
  110 |   await pick(page, "Park");
  111 |   await page.getByRole("button", { name: /plan my trip/i }).click();
  112 | 
  113 |   const firstStop = page.locator(".tl-name").first();
  114 |   await expect(firstStop).toBeVisible({ timeout: 60_000 });
  115 |   const before = (await firstStop.textContent()) ?? "";
  116 | 
  117 |   await page.locator(".tl-actions button", { hasText: "Swap" }).first().click();
  118 | 
> 119 |   await expect(page.getByText(/1 place skipped/i)).toBeVisible({ timeout: 60_000 });
      |                                                    ^ Error: expect(locator).toBeVisible() failed
  120 |   await expect(page.locator(".tl-name").first()).not.toHaveText(before);
  121 | 
  122 |   // And it can be undone.
  123 |   await page.getByRole("button", { name: /allow them again/i }).click();
  124 |   await expect(page.getByText(/place skipped/i)).toBeHidden({ timeout: 60_000 });
  125 | });
```