# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: auth.spec.ts >> a wrong password is refused with a clear message
- Location: e2e\auth.spec.ts:55:1

# Error details

```
Error: locator.fill: Target page, context or browser has been closed
Call log:
  - waiting for locator('#si-email')

```

```
Error: apiRequestContext._wrapApiCall: Target page, context or browser has been closed
```