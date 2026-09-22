import { Link, type ErrorComponentProps } from "@tanstack/react-router";
import { Compass, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

export function NotFound() {
  return (
    <main id="main" className="mx-auto flex min-h-[60vh] max-w-xl flex-col items-center justify-center px-6 py-16 text-center">
      <p className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">404</p>
      <h1 className="mt-3 font-display text-3xl font-semibold">This page wandered off</h1>
      <p className="mt-3 text-muted-foreground">
        The link may be old, or the plan may belong to another account. Plenty to find from here, though.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Button asChild>
          <Link to="/"><Compass aria-hidden="true" /> Back to Explore</Link>
        </Button>
        <Button asChild variant="secondary">
          <Link to="/ask">Ask NavigIQ</Link>
        </Button>
      </div>
    </main>
  );
}

export function RouteError({ reset }: ErrorComponentProps) {
  // Never show stack traces or raw errors to people.
  return (
    <main id="main" className="mx-auto flex min-h-[60vh] max-w-xl flex-col items-center justify-center px-6 py-16 text-center">
      <h1 className="font-display text-3xl font-semibold">Something went sideways</h1>
      <p className="mt-3 text-muted-foreground">
        This screen hit an unexpected problem. Your plans and saved places are safe.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Button onClick={() => { reset(); window.location.reload(); }}>
          <RotateCcw aria-hidden="true" /> Reload
        </Button>
        <Button asChild variant="secondary">
          <Link to="/">Go to Explore</Link>
        </Button>
      </div>
    </main>
  );
}

export function PageLoading() {
  return (
    <main id="main" className="mx-auto max-w-page px-4 py-10 sm:px-6 lg:px-8" aria-busy="true">
      <div className="skeleton h-9 w-64 rounded-xl" />
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((i) => <div key={i} className="skeleton h-72 rounded-3xl" />)}
      </div>
    </main>
  );
}
