import { ChevronLeft, ChevronRight } from "lucide-react";
import { useRef, type ReactNode } from "react";
import type { PoiCard } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { PoiFeatureCard } from "@/components/poi/PoiCard";
import { Skeleton } from "@/components/ui/primitives";

/** A horizontally scrolling row that snaps; arrows on pointer devices. */
export function Rail({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const scroll = (dir: 1 | -1) => {
    const el = ref.current;
    if (el) el.scrollBy({ left: dir * el.clientWidth * 0.85, behavior: "smooth" });
  };
  return (
    <div className={cn("group/rail relative", className)}>
      <div
        ref={ref}
        role="region"
        aria-label={label}
        tabIndex={0}
        className="scrollbar-none -mx-4 flex snap-x snap-mandatory gap-4 overflow-x-auto scroll-px-4 px-4 pb-4 pt-1 sm:-mx-6 sm:scroll-px-6 sm:px-6 lg:-mx-8 lg:scroll-px-8 lg:px-8"
      >
        {children}
      </div>
      <button
        type="button"
        onClick={() => scroll(-1)}
        aria-label={`Scroll ${label} back`}
        className="absolute -left-3 top-[38%] hidden size-11 place-items-center rounded-full bg-card shadow-lift ring-1 ring-border transition-opacity hover:bg-sand-50 lg:grid lg:opacity-0 lg:group-hover/rail:opacity-100 lg:focus-visible:opacity-100"
      >
        <ChevronLeft className="size-5" aria-hidden="true" />
      </button>
      <button
        type="button"
        onClick={() => scroll(1)}
        aria-label={`Scroll ${label} forward`}
        className="absolute -right-3 top-[38%] hidden size-11 place-items-center rounded-full bg-card shadow-lift ring-1 ring-border transition-opacity hover:bg-sand-50 lg:grid lg:opacity-0 lg:group-hover/rail:opacity-100 lg:focus-visible:opacity-100"
      >
        <ChevronRight className="size-5" aria-hidden="true" />
      </button>
    </div>
  );
}

export function PoiRail({ label, items, loading }: { label: string; items: PoiCard[] | undefined; loading?: boolean }) {
  if (loading) {
    return (
      <div className="flex gap-4 overflow-hidden" aria-busy="true" aria-label={`Loading ${label}`}>
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[22rem] w-[17rem] shrink-0 rounded-3xl" />)}
      </div>
    );
  }
  return (
    <Rail label={label}>
      {(items ?? []).map((poi, i) => (
        <div key={poi.id} className="w-[78vw] max-w-[18.5rem] shrink-0 snap-start sm:w-[17.5rem]">
          <PoiFeatureCard poi={poi} className="h-full" eager={i < 2} />
        </div>
      ))}
    </Rail>
  );
}

export function PoiGrid({ items, loading, count = 6 }: { items: PoiCard[] | undefined; loading?: boolean; count?: number }) {
  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
        {Array.from({ length: count }, (_, i) => <Skeleton key={i} className="h-80 rounded-3xl" />)}
      </div>
    );
  }
  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {(items ?? []).map((poi, i) => (
        <li key={poi.id} className="animate-rise" style={{ animationDelay: `${Math.min(i, 8) * 40}ms` }}>
          <PoiFeatureCard poi={poi} className="h-full" eager={i < 3} />
        </li>
      ))}
    </ul>
  );
}
