# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: plan.spec.ts >> a real plan shows at least 3 numbered stops on a map and a timeline
- Location: e2e\plan.spec.ts:32:1

# Error details

```
Test timeout of 90000ms exceeded.
```

```
Error: locator.fill: Test timeout of 90000ms exceeded.
Call log:
  - waiting for locator('#origin')

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - generic [ref=e4]: "[plugin:vite:react-babel] C:\\Users\\Sanjana K\\navigiq\\frontend\\src\\components\\Timeline.tsx: Expected corresponding JSX closing tag for <div>. (101:12) 104 | })}"
  - generic [ref=e5]: C:/Users/Sanjana K/navigiq/frontend/src/components/Timeline.tsx:101:12
  - generic [ref=e6]: 99 | </div> 100| </div> 101| </li> | ^ 102| </Fragment> 103| );
  - generic [ref=e7]: at constructor (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:369:19) at TypeScriptParserMixin.raise (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:6620:19) at TypeScriptParserMixin.jsxParseElementAt (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:4743:16) at TypeScriptParserMixin.jsxParseElementAt (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:4714:32) at TypeScriptParserMixin.jsxParseElementAt (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:4714:32) at TypeScriptParserMixin.jsxParseElement (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:4765:17) at TypeScriptParserMixin.parseExprAtom (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:4775:19) at TypeScriptParserMixin.parseExprSubscripts (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:11102:23) at TypeScriptParserMixin.parseUpdate (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:11087:21) at TypeScriptParserMixin.parseMaybeUnary (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:11067:23) at TypeScriptParserMixin.parseMaybeUnary (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:9858:18) at TypeScriptParserMixin.parseMaybeUnaryOrPrivate (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10920:61) at TypeScriptParserMixin.parseExprOps (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10925:23) at TypeScriptParserMixin.parseMaybeConditional (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10902:23) at TypeScriptParserMixin.parseMaybeAssign (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10852:21) at C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:9796:39 at TypeScriptParserMixin.tryParse (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:6928:20) at TypeScriptParserMixin.parseMaybeAssign (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:9796:18) at C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10821:39 at TypeScriptParserMixin.allowInAnd (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:12455:12) at TypeScriptParserMixin.parseMaybeAssignAllowIn (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10821:17) at TypeScriptParserMixin.parseMaybeAssignAllowInOrVoidPattern (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:12522:17) at TypeScriptParserMixin.parseParenAndDistinguishExpression (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:11701:28) at TypeScriptParserMixin.parseExprAtom (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:11357:23) at TypeScriptParserMixin.parseExprAtom (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:4780:20) at TypeScriptParserMixin.parseExprSubscripts (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:11102:23) at TypeScriptParserMixin.parseUpdate (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:11087:21) at TypeScriptParserMixin.parseMaybeUnary (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:11067:23) at TypeScriptParserMixin.parseMaybeUnary (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:9858:18) at TypeScriptParserMixin.parseMaybeUnaryOrPrivate (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10920:61) at TypeScriptParserMixin.parseExprOps (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10925:23) at TypeScriptParserMixin.parseMaybeConditional (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10902:23) at TypeScriptParserMixin.parseMaybeAssign (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10852:21) at TypeScriptParserMixin.parseMaybeAssign (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:9807:20) at TypeScriptParserMixin.parseExpressionBase (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10805:23) at C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10801:39 at TypeScriptParserMixin.allowInAnd (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:12450:16) at TypeScriptParserMixin.parseExpression (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:10801:17) at TypeScriptParserMixin.parseReturnStatement (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:13171:28) at TypeScriptParserMixin.parseStatementContent (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:12827:21) at TypeScriptParserMixin.parseStatementContent (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:9529:18) at TypeScriptParserMixin.parseStatementLike (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:12796:17) at TypeScriptParserMixin.parseStatementListItem (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:12776:17) at TypeScriptParserMixin.parseBlockOrModuleBlockBody (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:13345:61) at TypeScriptParserMixin.parseBlockBody (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:13338:10) at TypeScriptParserMixin.parseBlock (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:13326:10) at TypeScriptParserMixin.parseFunctionBody (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:12129:24) at TypeScriptParserMixin.parseArrowExpression (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:12104:10) at TypeScriptParserMixin.parseParenAndDistinguishExpression (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:11713:12) at TypeScriptParserMixin.parseExprAtom (C:\Users\Sanjana K\navigiq\frontend\node_modules\@babel\parser\lib\index.js:11357:23
  - generic [ref=e8]:
    - text: Click outside, press Esc key, or fix the code to dismiss.You can also disable this overlay by setting
    - code [ref=e9]: server.hmr.overlay
    - text: to
    - code [ref=e10]: "false"
    - text: in
    - code [ref=e11]: vite.config.ts
    - text: .
```

# Test source

```ts
  1   | import { expect, test, type Page } from "@playwright/test";
  2   | 
  3   | /**
  4   |  * NQ-026 definition of done:
  5   |  *  - fill the form, submit -> at least 3 markers on a map and a visible timeline
  6   |  *  - OpenStreetMap attribution is visible
  7   |  *  - an impossible request shows clickable fixes, not a blank screen
  8   |  *  - backend error codes each get their own screen
  9   |  */
  10  | 
  11  | /** Tomorrow as YYYY-MM-DD, so the test never plans a time that has passed. */
  12  | function tomorrow(): string {
  13  |   const d = new Date();
  14  |   d.setDate(d.getDate() + 1);
  15  |   return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  16  | }
  17  | 
  18  | async function startFrom(page: Page, place: string) {
  19  |   await page.goto("/#/plan");
> 20  |   await page.locator("#origin").fill(place);
      |                                 ^ Error: locator.fill: Test timeout of 90000ms exceeded.
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
  119 |   await expect(page.getByText(/1 place skipped/i)).toBeVisible({ timeout: 60_000 });
  120 |   await expect(page.locator(".tl-name").first()).not.toHaveText(before);
```