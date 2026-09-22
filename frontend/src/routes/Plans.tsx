import { Link } from "@tanstack/react-router";
import { CalendarPlus, Sparkles } from "lucide-react";
import { PageFooter } from "@/components/layout/AppShell";
import { PlanCard } from "@/components/plan/PlanStrip";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SectionHeader, Skeleton } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";
import { useDocumentTitle } from "@/lib/hooks";
import { usePlans } from "@/lib/queries";

export function PlansPage() {
  useDocumentTitle("Your plans");
  const q = usePlans();
  const { isAuthenticated } = useAuth();
  const plans = q.data?.plans ?? [];
  const upcoming = plans.filter((p) => p.status !== "abandoned");

  return (
    <>
      <main id="main" className="mx-auto max-w-page px-4 pb-10 pt-6 sm:px-6 lg:px-8">
        <SectionHeader
          title="Your plans"
          description="Every version is kept, so you can always go back to how a plan was."
          action={<Button asChild><Link to="/plans/new"><CalendarPlus aria-hidden="true" /> New plan</Link></Button>}
        />
        {q.isPending ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-52" />)}</div>
        ) : q.isError ? (
          <ErrorState description="Your plans didn't load." onRetry={() => void q.refetch()} />
        ) : upcoming.length === 0 ? (
          <EmptyState
            icon={<CalendarPlus aria-hidden="true" />}
            title="No plans yet"
            description="Tell NavigIQ what kind of day you want — it picks places that are open when you'd arrive, keeps you within budget and leaves room between stops."
            action={
              <>
                <Button asChild><Link to="/plans/new">Build a plan</Link></Button>
                <Button asChild variant="secondary">
                  <Link to="/ask" search={{ q: "Plan a relaxed Saturday with a garden, lunch and a museum under ₹1500", new: true }}>
                    <Sparkles aria-hidden="true" /> Or describe your day
                  </Link>
                </Button>
              </>
            }
          />
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {upcoming.map((p) => <li key={p.itinerary_id}><PlanCard plan={p} /></li>)}
          </ul>
        )}
        {!isAuthenticated && upcoming.length > 0 && (
          <p className="mt-6 rounded-2xl bg-info-soft px-4 py-3 text-sm text-info">
            These plans live in this browser. <Link to="/signin" className="font-semibold underline">Sign in</Link> and they'll follow you to your other devices.
          </p>
        )}
      </main>
      <PageFooter />
    </>
  );
}
