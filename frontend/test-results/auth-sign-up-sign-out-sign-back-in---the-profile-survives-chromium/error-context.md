# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: auth.spec.ts >> sign up, sign out, sign back in - the profile survives
- Location: e2e\auth.spec.ts:12:1

# Error details

```
Test timeout of 90000ms exceeded.
```

```
Error: locator.fill: Test timeout of 90000ms exceeded.
Call log:
  - waiting for locator('#email')

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
  1   | import { expect, test } from "@playwright/test";
  2   | 
  3   | /**
  4   |  * Real accounts, end to end against the real backend: sign up, fill the
  5   |  * profile, sign out, sign back in - and the profile is still there, because
  6   |  * it lives on the server now, not in the browser.
  7   |  */
  8   | 
  9   | const password = "planning123";
  10  | const email = () => `e2e${Date.now()}${Math.floor(Math.random() * 1000)}@e2e.navigiq.local`;
  11  | 
  12  | test("sign up, sign out, sign back in - the profile survives", async ({ page }) => {
  13  |   const address = email();
  14  | 
  15  |   // Step 1 - account (created on the server here)
  16  |   await page.goto("/#/welcome");
> 17  |   await page.locator("#email").fill(address);
      |                                ^ Error: locator.fill: Test timeout of 90000ms exceeded.
  18  |   await page.locator("#pw").fill(password);
  19  |   await page.locator("#confirm").fill(password);
  20  |   await page.getByRole("button", { name: /create account/i }).click();
  21  | 
  22  |   // Step 2 - about you
  23  |   await expect(page.getByRole("heading", { name: /about yourself/i })).toBeVisible();
  24  |   await page.locator("#name").fill("Test Traveller");
  25  |   await page.locator("#origin").fill("Koramangala");
  26  |   await page.locator(".place-options button").first().click();
  27  |   await page.getByRole("button", { name: /continue/i }).click();
  28  | 
  29  |   // Step 3 - preferences
  30  |   await page.getByRole("button", { name: /^Park/ }).click();
  31  |   await page.getByRole("button", { name: /^Vegetarian/ }).click();
  32  |   await page.getByRole("button", { name: /finish/i }).click();
  33  |   await expect(page.getByRole("heading", { name: /all set, test/i })).toBeVisible();
  34  | 
  35  |   // Sign out
  36  |   await page.goto("/#/profile");
  37  |   await page.getByRole("button", { name: /sign out/i }).click();
  38  |   await expect(page.getByRole("link", { name: /sign in/i })).toBeVisible();
  39  | 
  40  |   // Sign back in - with different capitalisation, which must still work
  41  |   await page.goto("/#/signin");
  42  |   await page.locator("#si-email").fill(address.toUpperCase());
  43  |   await page.locator("#si-pw").fill(password);
  44  |   await page.getByRole("button", { name: /sign in/i }).click();
  45  |   // Sign-in is asynchronous - wait until the header shows the account.
  46  |   await expect(page.locator(".avatar-link")).toBeVisible();
  47  | 
  48  |   // The profile came back from the server
  49  |   await page.goto("/#/profile");
  50  |   await expect(page.locator("#pname")).toHaveValue("Test Traveller");
  51  |   await expect(page.locator(".picked")).toContainText("Koramangala");
  52  |   await expect(page.getByLabel(/vegetarian food only/i)).toBeChecked();
  53  | });
  54  | 
  55  | test("a wrong password is refused with a clear message", async ({ page }) => {
  56  |   await page.goto("/#/signin");
  57  |   await page.locator("#si-email").fill("nobody@e2e.navigiq.local");
  58  |   await page.locator("#si-pw").fill("wrongpass1");
  59  |   await page.getByRole("button", { name: /sign in/i }).click();
  60  |   await expect(page.getByRole("alert")).toContainText("don't match");
  61  | });
  62  | 
  63  | test("signing up twice with the same email is refused", async ({ page }) => {
  64  |   const address = email();
  65  |   for (let attempt = 0; attempt < 2; attempt++) {
  66  |     await page.goto("/#/profile");
  67  |     const signOut = page.getByRole("button", { name: /sign out/i });
  68  |     if (await signOut.isVisible().catch(() => false)) await signOut.click();
  69  | 
  70  |     await page.goto("/#/welcome");
  71  |     await page.locator("#email").fill(address);
  72  |     await page.locator("#pw").fill(password);
  73  |     await page.locator("#confirm").fill(password);
  74  |     await page.getByRole("button", { name: /create account/i }).click();
  75  |     if (attempt === 0) await expect(page.getByRole("heading", { name: /about yourself/i })).toBeVisible();
  76  |   }
  77  |   await expect(page.getByText(/already exists/i)).toBeVisible();
  78  | });
  79  | 
  80  | test("deleting the account needs the password, and then it's gone", async ({ page }) => {
  81  |   const address = email();
  82  |   await page.goto("/#/welcome");
  83  |   await page.locator("#email").fill(address);
  84  |   await page.locator("#pw").fill(password);
  85  |   await page.locator("#confirm").fill(password);
  86  |   await page.getByRole("button", { name: /create account/i }).click();
  87  |   await expect(page.getByRole("heading", { name: /about yourself/i })).toBeVisible();
  88  | 
  89  |   await page.goto("/#/profile");
  90  |   await page.getByRole("button", { name: /delete my account/i }).click();
  91  | 
  92  |   // Wrong password: refused, account kept.
  93  |   await page.locator("#del-pw").fill("wrongpass1");
  94  |   await page.getByRole("button", { name: /delete permanently/i }).click();
  95  |   await expect(page.getByRole("alert")).toContainText("isn't right");
  96  | 
  97  |   // Right password: deleted and signed out.
  98  |   await page.locator("#del-pw").fill(password);
  99  |   await page.getByRole("button", { name: /delete permanently/i }).click();
  100 |   await expect(page.getByRole("link", { name: /sign in/i })).toBeVisible();
  101 | 
  102 |   // The account really is gone.
  103 |   await page.goto("/#/signin");
  104 |   await page.locator("#si-email").fill(address);
  105 |   await page.locator("#si-pw").fill(password);
  106 |   await page.getByRole("button", { name: /sign in/i }).click();
  107 |   await expect(page.getByRole("alert")).toContainText("don't match");
  108 | });
  109 | 
```