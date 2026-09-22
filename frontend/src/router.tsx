/**
 * Routes. Code-based TanStack Router; every screen is its own chunk so the
 * first load only pays for the screen being opened.
 */
import { createRootRouteWithContext, createRoute, createRouter, lazyRouteComponent } from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/AppShell";
import { NotFound, RouteError } from "@/components/layout/RouteStates";

export interface RouterContext {
  queryClient: QueryClient;
}

const str = (v: unknown): string | undefined => (typeof v === "string" && v.trim() ? v.trim().slice(0, 300) : undefined);
const num = (v: unknown): number | undefined => {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN;
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : undefined;
};
const list = (v: unknown): string[] | undefined => {
  if (Array.isArray(v)) return v.filter((x): x is string => typeof x === "string").slice(0, 8);
  if (typeof v === "string" && v) return v.split(",").slice(0, 8);
  return undefined;
};

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: AppShell,
  notFoundComponent: NotFound,
  errorComponent: RouteError,
});

const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: lazyRouteComponent(() => import("@/routes/Home"), "HomePage"),
});

export interface SearchParams {
  q?: string;
  category?: string[];
  mood?: string;
  area?: string;
  scope?: "city" | "regional" | "anywhere";
  max_cost?: number;
  view?: "list" | "map";
}

const searchRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/search",
  validateSearch: (s: Record<string, unknown>): SearchParams => ({
    q: str(s.q),
    category: list(s.category),
    mood: str(s.mood),
    area: str(s.area),
    scope: s.scope === "city" || s.scope === "regional" || s.scope === "anywhere" ? s.scope : undefined,
    max_cost: num(s.max_cost),
    view: s.view === "map" ? "map" : undefined,
  }),
  component: lazyRouteComponent(() => import("@/routes/Search"), "SearchPage"),
});

const askRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/ask",
  validateSearch: (s: Record<string, unknown>): { q?: string; new?: boolean } => ({
    q: str(s.q),
    new: s.new === true || s.new === "true" ? true : undefined,
  }),
  component: lazyRouteComponent(() => import("@/routes/Ask"), "AskPage"),
});

const boredRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/bored",
  validateSearch: (s: Record<string, unknown>): { surprise?: boolean } => ({
    surprise: s.surprise === true || s.surprise === "true" ? true : undefined,
  }),
  component: lazyRouteComponent(() => import("@/routes/Bored"), "BoredPage"),
});

const placeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/places/$placeId",
  component: lazyRouteComponent(() => import("@/routes/Place"), "PlacePage"),
});

const collectionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/collections",
  component: lazyRouteComponent(() => import("@/routes/Collections"), "CollectionsPage"),
});

const collectionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/collections/$collectionId",
  component: lazyRouteComponent(() => import("@/routes/Collections"), "CollectionPage"),
});

const plansRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/plans",
  component: lazyRouteComponent(() => import("@/routes/Plans"), "PlansPage"),
});

export interface NewPlanSearch {
  interests?: string[];
  include?: number;
  days?: number;
}

const newPlanRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/plans/new",
  validateSearch: (s: Record<string, unknown>): NewPlanSearch => ({
    interests: list(s.interests),
    include: num(s.include),
    days: num(s.days),
  }),
  component: lazyRouteComponent(() => import("@/routes/PlanNew"), "PlanNewPage"),
});

const planRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/plans/$planId",
  validateSearch: (s: Record<string, unknown>): { version?: number } => ({ version: num(s.version) }),
  component: lazyRouteComponent(() => import("@/routes/Plan"), "PlanPage"),
});

const savedRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/saved",
  component: lazyRouteComponent(() => import("@/routes/Saved"), "SavedPage"),
});

const profileRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/profile",
  component: lazyRouteComponent(() => import("@/routes/Profile"), "ProfilePage"),
});

const authSearch = (s: Record<string, unknown>): { redirect?: string } => {
  const r = str(s.redirect);
  // Only same-app paths: never redirect to another origin after sign-in.
  return { redirect: r && r.startsWith("/") && !r.startsWith("//") ? r : undefined };
};

const signInRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/signin",
  validateSearch: authSearch,
  component: lazyRouteComponent(() => import("@/routes/Auth"), "SignInPage"),
});

const signUpRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/signup",
  validateSearch: authSearch,
  component: lazyRouteComponent(() => import("@/routes/Auth"), "SignUpPage"),
});

const routeTree = rootRoute.addChildren([
  homeRoute, searchRoute, askRoute, boredRoute, placeRoute, collectionsRoute, collectionRoute,
  plansRoute, newPlanRoute, planRoute, savedRoute, profileRoute, signInRoute, signUpRoute,
]);

export function createAppRouter(queryClient: QueryClient) {
  return createRouter({
    routeTree,
    context: { queryClient },
    defaultPreload: "intent",
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
