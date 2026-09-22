/** A compact itinerary for chat and lists: days, stops and totals; opens the full plan. */
import { Link } from "@tanstack/react-router";
import { ArrowRight, CalendarDays, ShieldCheck } from "lucide-react";
import type { Itinerary } from "@/lib/api/types";
import { categoryMeta } from "@/lib/categories";
import { cn } from "@/lib/cn";
import { clock, costLabel, dateLabel, dateRangeLabel, plural } from "@/lib/format";
import { daysOf, isTrip, localSeq } from "@/lib/plan";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/primitives";

export function ItineraryPreview({ it, validated = true, className, maxStops = 6 }: {
  it: Itinerary; validated?: boolean; className?: string; maxStops?: number;
}) {
  const days = daysOf(it);
  const trip = isTrip(it);
  const s = it.summary;
  let shown = 0;
  return (
    <article className={cn("overflow-hidden rounded-3xl bg-card shadow-soft ring-1 ring-border/60", className)}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border/70 bg-sand-50 px-5 py-4">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <CalendarDays className="size-3.5" aria-hidden="true" />
            {trip ? dateRangeLabel(it.date, it.end_date) : `${dateLabel(it.date, true)} · ${clock(it.start_time)}–${clock(it.end_time)}`}
          </p>
          <h3 className="mt-1 font-display text-lg font-semibold">{it.title}</h3>
        </div>
        {validated && (
          <Badge tone="success" title="Every stop passed NavigIQ's independent checks">
            <ShieldCheck aria-hidden="true" /> Checked
          </Badge>
        )}
      </header>
      <div className="space-y-4 px-5 py-4">
        {days.map((d) => {
          if (shown >= maxStops) return null;
          const stops = d.stops.slice(0, Math.max(0, maxStops - shown));
          shown += stops.length;
          return (
            <div key={d.day}>
              {trip && (
                <p className="mb-2 text-xs font-semibold text-muted-foreground">
                  Day {d.day} · {dateLabel(d.date)}{d.title ? ` · ${d.title}` : ""}
                </p>
              )}
              <ol className="space-y-2">
                {stops.map((st) => {
                  const Icon = categoryMeta(st.poi.category).icon;
                  return (
                    <li key={st.seq} className="flex items-center gap-3 text-sm">
                      <span className="grid size-7 shrink-0 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground" aria-hidden="true">
                        {localSeq(st)}
                      </span>
                      <span className="w-16 shrink-0 tabular-nums text-muted-foreground">{clock(st.arrive)}</span>
                      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                      <span className="min-w-0 truncate font-medium">{st.poi.name}</span>
                    </li>
                  );
                })}
              </ol>
            </div>
          );
        })}
        {s.stop_count > shown && (
          <p className="text-sm text-muted-foreground">+ {plural(s.stop_count - shown, "more stop")}</p>
        )}
      </div>
      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border/70 px-5 py-3.5">
        <p className="text-sm">
          <span className="font-semibold">{costLabel(s.estimated_cost)}</span>
          <span className="text-muted-foreground"> est. for {plural(s.party_size, "person", "people")} · excludes transport</span>
        </p>
        {it.itinerary_id && (
          <Button asChild size="sm">
            <Link to="/plans/$planId" params={{ planId: String(it.itinerary_id) }}>
              Open plan <ArrowRight aria-hidden="true" />
            </Link>
          </Button>
        )}
      </footer>
    </article>
  );
}
