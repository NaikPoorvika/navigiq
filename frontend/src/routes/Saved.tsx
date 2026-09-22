import { Link } from "@tanstack/react-router";
import { Bookmark, CalendarPlus, Compass } from "lucide-react";
import { useMemo, useState } from "react";
import { PageFooter } from "@/components/layout/AppShell";
import { PoiGrid } from "@/components/poi/PoiRail";
import { Button } from "@/components/ui/button";
import { Chip, EmptyState, ErrorState, SectionHeader } from "@/components/ui/primitives";
import { categoryMeta } from "@/lib/categories";
import { useAuth } from "@/lib/auth";
import { useDocumentTitle } from "@/lib/hooks";
import { useSaved } from "@/lib/queries";

export function SavedPage() {
  useDocumentTitle("Saved places");
  const { isAuthenticated } = useAuth();
  const q = useSaved();
  const items = useMemo(() => q.data?.items ?? [], [q.data]);
  const [category, setCategory] = useState<string | null>(null);
  const categories = useMemo(() => [...new Set(items.map((i) => i.category))], [items]);
  const shown = category ? items.filter((i) => i.category === category) : items;

  if (!isAuthenticated) {
    return (
      <>
        <main id="main" className="mx-auto max-w-2xl px-4 py-16 sm:px-6">
          <EmptyState
            icon={<Bookmark aria-hidden="true" />}
            title="Saved places need an account"
            description="Everything else works without one — explore, ask and plan. Signing in keeps your saved places and plans across devices."
            action={
              <>
                <Button asChild><Link to="/signup">Create an account</Link></Button>
                <Button asChild variant="secondary"><Link to="/signin">Sign in</Link></Button>
              </>
            }
          />
        </main>
        <PageFooter />
      </>
    );
  }

  return (
    <>
      <main id="main" className="mx-auto max-w-page px-4 pb-10 pt-6 sm:px-6 lg:px-8">
        <SectionHeader
          title="Saved places"
          description={items.length ? `${items.length} place${items.length === 1 ? "" : "s"} you've kept.` : undefined}
          action={items.length > 0 ? <Button asChild variant="secondary"><Link to="/plans/new"><CalendarPlus aria-hidden="true" /> Plan around them</Link></Button> : undefined}
        />
        {q.isError ? (
          <ErrorState description="Your saved places didn't load." onRetry={() => void q.refetch()} />
        ) : q.isPending ? (
          <PoiGrid items={[]} loading count={6} />
        ) : items.length === 0 ? (
          <EmptyState
            icon={<Bookmark aria-hidden="true" />}
            title="Nothing saved yet"
            description="Tap the bookmark on any place to keep it here. Saved places also nudge what NavigIQ recommends for you."
            action={<Button asChild><Link to="/"><Compass aria-hidden="true" /> Find something to save</Link></Button>}
          />
        ) : (
          <>
            {categories.length > 1 && (
              <div className="mb-5 flex flex-wrap gap-2">
                <Chip selected={category === null} onClick={() => setCategory(null)} className="h-9">All</Chip>
                {categories.map((c) => (
                  <Chip key={c} selected={category === c} onClick={() => setCategory(c)} className="h-9">{categoryMeta(c).label}</Chip>
                ))}
              </div>
            )}
            <PoiGrid items={shown} />
          </>
        )}
      </main>
      <PageFooter />
    </>
  );
}
