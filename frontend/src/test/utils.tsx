/** Test helpers: render a component inside the app's real providers. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet,
} from "@tanstack/react-router";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";
import { Toaster } from "sonner";
import { AuthProvider } from "@/lib/auth";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
}

/**
 * Renders `ui` at "/" inside a memory router (so <Link> and navigation work)
 * plus React Query and auth. Extra routes can be declared for navigation
 * assertions.
 */
export function renderApp(ui: ReactNode, { path = "/" }: { path?: string } = {}): RenderResult & { queryClient: QueryClient } {
  const queryClient = makeQueryClient();
  const rootRoute = createRootRoute({ component: () => <Outlet /> });
  const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: () => <>{ui}</> });
  const placeRoute = createRoute({ getParentRoute: () => rootRoute, path: "/places/$placeId", component: () => <p>Place page</p> });
  const planRoute = createRoute({ getParentRoute: () => rootRoute, path: "/plans/$planId", component: () => <p>Plan page</p> });
  const signinRoute = createRoute({ getParentRoute: () => rootRoute, path: "/signin", component: () => <p>Sign in page</p> });
  const newPlanRoute = createRoute({ getParentRoute: () => rootRoute, path: "/plans/new", component: () => <p>New plan page</p> });
  const askRoute = createRoute({ getParentRoute: () => rootRoute, path: "/ask", component: () => <p>Ask page</p> });
  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute, placeRoute, planRoute, signinRoute, newPlanRoute, askRoute]),
    history: createMemoryHistory({ initialEntries: [path] }),
    context: { queryClient },
  });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        <RouterProvider router={router as any} />
        <Toaster />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return Object.assign(result, { queryClient });
}
