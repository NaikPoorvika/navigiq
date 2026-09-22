/** Curated collections: themed slices of the catalogue, built by the backend. */
import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, Layers } from "lucide-react";
import { PageFooter } from "@/components/layout/AppShell";
import { PoiGrid } from "@/components/poi/PoiRail";
import { CategoryArt } from "@/components/poi/PoiArt";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SectionHeader, Skeleton } from "@/components/ui/primitives";
import { GROUP_TONE } from "@/lib/categories";
import { cn } from "@/lib/cn";
import { GROUP_CATEGORY, collectionLook } from "@/lib/collections";
import { useDocumentTitle } from "@/lib/hooks";
import { useCollections } from "@/lib/queries";

export function CollectionsPage() {
  useDocumentTitle("Collections");
  const q = useCollections();
  const available = q.data?.available ?? [];
  return (
    <>
      <main id="main" className="mx-auto max-w-page px-4 pb-10 pt-6 sm:px-6 lg:px-8">
        <SectionHeader
          eyebrow="Explore"
          title="Collections"
          description="Themed picks built from NavigIQ's own data — not sponsored, not scraped from review sites."
        />
        {q.isPending ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-44" />)}</div>
        ) : q.isError ? (
          <ErrorState description="Collections didn't load." onRetry={() => void q.refetch()} />
        ) : (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {available.map((c) => {
              const look = collectionLook(c.id);
              const tone = GROUP_TONE[look.group];
              return (
                <li key={c.id}>
                  <Link to="/collections/$collectionId" params={{ collectionId: c.id }}
                    className="group relative block h-44 overflow-hidden rounded-3xl shadow-soft ring-1 ring-border/50">
                    {look.art ? (
                      <>
                        <img src={look.art.src} alt="" loading="lazy" className="absolute inset-0 size-full object-cover transition-transform duration-500 group-hover:scale-[1.04]" />
                        <div className="absolute inset-0 bg-gradient-to-t from-olive-950/85 via-olive-950/25 to-transparent" aria-hidden="true" />
                      </>
                    ) : (
                      <>
                        <CategoryArt category={GROUP_CATEGORY[look.group] ?? "other"} seed={c.id} className={cn("absolute inset-0 size-full", tone.bg)} iconSize="lg" />
                        <div className="absolute inset-x-0 bottom-0 h-3/5 bg-gradient-to-t from-card via-card/85 to-transparent" aria-hidden="true" />
                      </>
                    )}
                    <div className={cn("absolute inset-x-0 bottom-0 p-4", look.art ? "text-white" : tone.ink)}>
                      <p className="font-display text-base font-semibold leading-tight">{c.title}</p>
                      {c.subtitle && <p className={cn("mt-1 line-clamp-2 text-xs", look.art ? "text-white/80" : "opacity-80")}>{c.subtitle}</p>}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </main>
      <PageFooter />
    </>
  );
}

export function CollectionPage() {
  const { collectionId } = useParams({ from: "/collections/$collectionId" });
  const q = useCollections([collectionId]);
  const collection = q.data?.collections.find((c) => c.id === collectionId);
  const definition = q.data?.available.find((c) => c.id === collectionId);
  useDocumentTitle(collection?.title ?? definition?.title ?? "Collection");

  return (
    <>
      <main id="main" className="mx-auto max-w-page px-4 pb-10 pt-6 sm:px-6 lg:px-8">
        <nav aria-label="Breadcrumb" className="text-sm">
          <Link to="/collections" className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-4" aria-hidden="true" /> Collections
          </Link>
        </nav>
        {q.isPending ? (
          <>
            <Skeleton className="mt-4 h-10 w-1/2" />
            <div className="mt-6"><PoiGrid items={[]} loading /></div>
          </>
        ) : q.isError ? (
          <ErrorState className="mt-6" description="This collection didn't load." onRetry={() => void q.refetch()} />
        ) : !collection || collection.items.length === 0 ? (
          <EmptyState
            className="mt-6"
            icon={<Layers aria-hidden="true" />}
            title={definition ? `Nothing in ${definition.title} right now` : "We don't have that collection"}
            description="Collections are rebuilt from live data, so they can be empty if nothing qualifies today."
            action={<Button asChild><Link to="/collections">See all collections</Link></Button>}
          />
        ) : (
          <>
            <SectionHeader className="mt-4" title={collection.title} description={collection.subtitle ?? undefined} />
            <PoiGrid items={collection.items} />
            <p className="mt-6 text-xs text-muted-foreground">
              Ranked by how well each place fits this theme, its data quality and how far it is — the same engine the planner uses.
            </p>
          </>
        )}
      </main>
      <PageFooter />
    </>
  );
}
