/**
 * The HTTP client's contract with the backend: session header, stable error
 * codes, and one silent refresh on 401. The API itself is mocked here (MSW);
 * the real API is covered by the Playwright suite.
 */
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { ApiError, api, refreshSession } from "@/lib/api/client";
import { tokenStore } from "@/lib/api/tokens";
import { getSessionId } from "@/lib/session";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  tokenStore.clear();
});
afterAll(() => server.close());

describe("api client", () => {
  it("sends the anonymous session with every request", async () => {
    let seen: string | null = null;
    server.use(http.get("/api/v1/plans", ({ request }) => {
      seen = request.headers.get("X-NavigIQ-Session");
      return HttpResponse.json({ plans: [] });
    }));
    await api.get("/plans");
    expect(seen).toBe(getSessionId());
    expect(seen).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
  });

  it("builds query strings without sending empty values", async () => {
    let url = "";
    server.use(http.get("/api/v1/pois", ({ request }) => {
      url = new URL(request.url).search;
      return HttpResponse.json({ items: [] });
    }));
    await api.get("/pois", { q: "lake", category: ["park", "lake"], area: undefined, limit: 5, scope: "" });
    expect(url).toBe("?q=lake&category=park&category=lake&limit=5");
  });

  it("surfaces the backend's error code and message", async () => {
    server.use(http.post("/api/v1/plans", () => HttpResponse.json(
      { error: { code: "INFEASIBLE", message: "No arrangement fits.", details: { feasibility: { feasible: false } } } },
      { status: 409 },
    )));
    const err = (await api.post("/plans", {}).catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("INFEASIBLE");
    expect(err.status).toBe(409);
    expect(err.details).toMatchObject({ feasibility: { feasible: false } });
  });

  it("reads FastAPI's detail wrapper too", async () => {
    server.use(http.get("/api/v1/plans/1", () => HttpResponse.json(
      { detail: { error: { code: "NOT_FOUND", message: "plan not found" } } }, { status: 404 },
    )));
    const err = (await api.get("/plans/1").catch((e) => e)) as ApiError;
    expect(err.code).toBe("NOT_FOUND");
  });

  it("turns a dropped connection into a network error, not a crash", async () => {
    server.use(http.get("/api/v1/context", () => HttpResponse.error()));
    const err = (await api.get("/context").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isNetwork).toBe(true);
    expect(err.message).toMatch(/connection/i);
  });

  it("refreshes the access token once on 401 and retries", async () => {
    tokenStore.set({
      access_token: "old", refresh_token: "r1", token_type: "bearer", expires_in: 900,
      user: { id: "u1", email: "a@b.com", display_name: null, is_active: true },
    });
    let calls = 0;
    const seen: (string | null)[] = [];
    server.use(
      http.get("/api/v1/me/saved", ({ request }) => {
        calls += 1;
        seen.push(request.headers.get("Authorization"));
        if (calls === 1) return HttpResponse.json({ error: { code: "TOKEN_INVALID", message: "expired" } }, { status: 401 });
        return HttpResponse.json({ items: [] });
      }),
      http.post("/api/v1/auth/refresh", () => HttpResponse.json({
        access_token: "new", refresh_token: "r2", token_type: "bearer", expires_in: 900,
        user: { id: "u1", email: "a@b.com", display_name: null, is_active: true },
      })),
    );
    await api.get("/me/saved");
    expect(calls).toBe(2);
    expect(seen).toEqual(["Bearer old", "Bearer new"]);
    expect(tokenStore.refreshToken).toBe("r2");
  });

  it("refreshes once even when several requests hit 401 together", async () => {
    // The backend rotates refresh tokens: a second, parallel refresh with the
    // same token would fail and sign the person out. (Regression: React's
    // double-invoked effects used to do exactly that on page load.)
    tokenStore.set({
      access_token: "old", refresh_token: "r1", token_type: "bearer", expires_in: 900,
      user: { id: "u1", email: "a@b.com", display_name: null, is_active: true },
    });
    let refreshes = 0;
    server.use(
      http.get("/api/v1/me", ({ request }) =>
        request.headers.get("Authorization") === "Bearer new"
          ? HttpResponse.json({ id: "u1" })
          : HttpResponse.json({ error: { code: "TOKEN_INVALID", message: "expired" } }, { status: 401 })),
      http.get("/api/v1/me/saved", ({ request }) =>
        request.headers.get("Authorization") === "Bearer new"
          ? HttpResponse.json({ items: [] })
          : HttpResponse.json({ error: { code: "TOKEN_INVALID", message: "expired" } }, { status: 401 })),
      http.post("/api/v1/auth/refresh", () => {
        refreshes += 1;
        if (refreshes > 1) return HttpResponse.json({ error: { code: "REFRESH_INVALID", message: "used" } }, { status: 401 });
        return HttpResponse.json({
          access_token: "new", refresh_token: "r2", token_type: "bearer", expires_in: 900,
          user: { id: "u1", email: "a@b.com", display_name: null, is_active: true },
        });
      }),
    );
    await Promise.all([api.get("/me"), api.get("/me/saved"), refreshSession()]);
    expect(refreshes).toBe(1);
    expect(tokenStore.refreshToken).toBe("r2");
  });

  it("keeps the session when the refresh request fails on the network", async () => {
    tokenStore.set({
      access_token: "old", refresh_token: "r1", token_type: "bearer", expires_in: 900,
      user: { id: "u1", email: "a@b.com", display_name: null, is_active: true },
    });
    server.use(http.post("/api/v1/auth/refresh", () => HttpResponse.error()));
    expect(await refreshSession()).toBe(false);
    expect(tokenStore.refreshToken).toBe("r1");
  });

  it("signs out when the refresh token is rejected", async () => {
    tokenStore.set({
      access_token: "old", refresh_token: "bad", token_type: "bearer", expires_in: 900,
      user: { id: "u1", email: "a@b.com", display_name: null, is_active: true },
    });
    server.use(
      http.get("/api/v1/me", () => HttpResponse.json({ error: { code: "TOKEN_INVALID", message: "expired" } }, { status: 401 })),
      http.post("/api/v1/auth/refresh", () => HttpResponse.json({ error: { code: "REFRESH_INVALID", message: "no" } }, { status: 401 })),
    );
    const err = (await api.get("/me").catch((e) => e)) as ApiError;
    expect(err.status).toBe(401);
    expect(tokenStore.refreshToken).toBeNull();
    expect(tokenStore.user).toBeNull();
  });
});
