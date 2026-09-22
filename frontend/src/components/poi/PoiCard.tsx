/**
 * Place cards. Progressive disclosure: the essentials (what, where, rough
 * cost and time) always; the "why" — reason texts from the ranking engine,
 * never invented — when the place was recommended.
 */
import { Link } from "@tanstack/react-router";
import { Clock3, MapPin, Sparkles } from "lucide-react";
import type { PoiCard as Poi, ScoredPoi } from "@/lib/api/types";
import { GROUP_TONE, categoryMeta } from "@/lib/categories";
import { cn } from "@/lib/cn";
import { costShort, durationLabel, regionLabel } from "@/lib/format";
import { Badge } from "@/components/ui/primitives";
import { PoiArt } from "@/components/poi/PoiArt";
import { SaveButton } from "@/components/poi/SaveButton";

function isScored(p: Poi): p is ScoredPoi {
  return Array.isArray((p as ScoredPoi).why);
}

export function whereLabel(poi: Poi): string {
  const bits = [poi.locality, poi.region_bucket === "NEARBY_ESCAPE" || poi.region_bucket === "OUTSKIRTS"
    ? regionLabel(poi.region_bucket) : null].filter(Boolean);
  return bits.join(" · ") || regionLabel(poi.region_bucket);
}

export function CategoryBadge({ category, className }: { category: string; className?: string }) {
  const meta = categoryMeta(category);
  const tone = GROUP_TONE[meta.group];
  const Icon = meta.icon;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold", tone.bg, tone.ink, className)}>
      <Icon className="size-3.5" aria-hidden="true" />
      {meta.label}
    </span>
  );
}

function Facts({ poi, className }: { poi: Poi; className?: string }) {
  return (
    <p className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground", className)}>
      <span className="font-semibold text-foreground" title="Estimated cost per person">
        {costShort(poi.estimated_cost)}
        {poi.estimated_cost.max > 0 && <span className="font-normal text-muted-foreground"> /person est.</span>}
      </span>
      <span className="inline-flex items-center gap-1">
        <Clock3 className="size-3.5" aria-hidden="true" />
        {durationLabel(poi.visit_duration)}
      </span>
    </p>
  );
}

/** Large card for rails and grids. */
export function PoiFeatureCard({ poi, className, eager, rank }: { poi: Poi; className?: string; eager?: boolean; rank?: number }) {
  const why = isScored(poi) ? poi.why.filter(Boolean).slice(0, 2) : [];
  return (
    <article className={cn("group relative flex flex-col overflow-hidden rounded-3xl bg-card shadow-soft ring-1 ring-border/60 transition-[box-shadow,transform] duration-300 hover:-translate-y-0.5 hover:shadow-lift has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-ring", className)}>
      <div className="relative">
        <PoiArt poi={poi} className="aspect-[4/3] w-full" eager={eager} />
        <div className="absolute left-3 top-3 flex flex-wrap gap-1.5">
          <CategoryBadge category={poi.category} className="bg-card/90 backdrop-blur" />
          {poi.estimated_cost.max === 0 && <Badge tone="success" className="bg-success-soft/95">Free</Badge>}
          {poi.recommended_as_primary_destination && <Badge tone="info" className="bg-info-soft/95">Day trip</Badge>}
        </div>
        <SaveButton poi={poi} variant="overlay" className="absolute right-3 top-3 z-10" />
        {rank !== undefined && (
          <span className="absolute bottom-3 left-3 grid size-8 place-items-center rounded-full bg-card/90 font-display text-sm font-semibold shadow-soft" aria-hidden="true">
            {rank}
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-4">
        <h3 className="font-display text-[1.05rem] font-semibold leading-snug">
          <Link to="/places/$placeId" params={{ placeId: String(poi.id) }} className="after:absolute after:inset-0 focus-visible:outline-none">
            {poi.name}
          </Link>
        </h3>
        <p className="flex items-center gap-1 text-[13px] text-muted-foreground">
          <MapPin className="size-3.5 shrink-0" aria-hidden="true" />
          <span className="truncate">{whereLabel(poi)}</span>
        </p>
        {poi.short_description && (
          <p className="line-clamp-2 text-sm text-foreground/80">{poi.short_description}</p>
        )}
        {why.length > 0 && (
          <p className="flex items-start gap-1.5 text-[13px] text-primary">
            <Sparkles className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            <span><span className="sr-only">Why it's suggested: </span>{why.join(" · ")}</span>
          </p>
        )}
        <Facts poi={poi} className="mt-auto pt-2" />
      </div>
    </article>
  );
}

/** Compact row: lists, chat results, search. */
export function PoiRowCard({ poi, className, trailing, onSelect, selected }: {
  poi: Poi; className?: string; trailing?: React.ReactNode; onSelect?: () => void; selected?: boolean;
}) {
  const why = isScored(poi) ? poi.why.filter(Boolean).slice(0, 1) : [];
  return (
    <article
      className={cn(
        "group relative flex gap-3.5 rounded-2xl bg-card p-2.5 pr-3 ring-1 ring-border/70 transition-shadow hover:shadow-soft has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-ring",
        selected && "ring-2 ring-primary",
        className,
      )}
      onMouseEnter={onSelect}
    >
      <PoiArt poi={poi} className="size-20 shrink-0 rounded-xl sm:size-24" iconSize="sm" credit="none" />
      <div className="flex min-w-0 flex-1 flex-col justify-center gap-1 py-0.5">
        <p className="text-xs font-semibold text-muted-foreground">{categoryMeta(poi.category).label}</p>
        <h3 className="font-display text-[0.98rem] font-semibold leading-snug">
          <Link to="/places/$placeId" params={{ placeId: String(poi.id) }} className="after:absolute after:inset-0 focus-visible:outline-none">
            {poi.name}
          </Link>
        </h3>
        <p className="truncate text-[13px] text-muted-foreground">{whereLabel(poi)}</p>
        {why.length > 0 ? (
          <p className="truncate text-[13px] text-primary">{why[0]}</p>
        ) : (
          <Facts poi={poi} />
        )}
      </div>
      <div className="relative z-10 flex shrink-0 flex-col items-end justify-between">
        <SaveButton poi={poi} />
        {trailing}
      </div>
    </article>
  );
}
