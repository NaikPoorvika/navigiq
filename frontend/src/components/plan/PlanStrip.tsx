import { Link } from "@tanstack/react-router";
import { ArrowUpRight, CalendarDays, MapPin } from "lucide-react";
import type { PlanListItem } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { costShort, dateRangeLabel, plural, relativeDay } from "@/lib/format";
import { Badge } from "@/components/ui/primitives";

export function PlanCard({ plan, className }: { plan: PlanListItem; className?: string }) {
  const rel = plan.date && plan.day_count <= 1 ? relativeDay(plan.date) : null;
  return (
    <article className={cn("group relative flex h-full flex-col rounded-3xl bg-card p-5 shadow-soft ring-1 ring-border/60 transition-shadow hover:shadow-lift has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-ring", className)}>
      <div className="flex items-center justify-between gap-3">
        <p className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
          <CalendarDays className="size-4" aria-hidden="true" />
          {rel ?? (plan.date ? dateRangeLabel(plan.date, plan.end_date) : "Undated")}
        </p>
        <div className="flex gap-1.5">
          {plan.day_count > 1 && <Badge tone="info">{plan.day_count} days</Badge>}
          {plan.status === "saved" && <Badge tone="primary">Saved</Badge>}
        </div>
      </div>
      <h3 className="mt-3 font-display text-lg font-semibold leading-snug">
        <Link to="/plans/$planId" params={{ planId: String(plan.itinerary_id) }} className="after:absolute after:inset-0 focus-visible:outline-none">
          {plan.title}
        </Link>
      </h3>
      {plan.stops_preview.length > 0 && (
        <ol className="mt-3 space-y-1.5 text-sm text-foreground/80">
          {plan.stops_preview.slice(0, 3).map((name, i) => (
            <li key={`${name}-${i}`} className="flex items-center gap-2">
              <span className="grid size-5 shrink-0 place-items-center rounded-full bg-primary-soft text-[11px] font-semibold text-primary">{i + 1}</span>
              <span className="truncate">{name}</span>
            </li>
          ))}
        </ol>
      )}
      <div className="mt-auto flex items-center justify-between pt-4 text-sm text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <MapPin className="size-4" aria-hidden="true" />
          {plural(plan.stop_count, "stop")}
          {plan.estimated_cost && <> · {costShort(plan.estimated_cost)} est.</>}
        </span>
        <ArrowUpRight className="size-4 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden="true" />
      </div>
    </article>
  );
}

export function PlanStrip({ plans }: { plans: PlanListItem[] }) {
  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {plans.map((p) => (
        <li key={p.itinerary_id}><PlanCard plan={p} /></li>
      ))}
    </ul>
  );
}
