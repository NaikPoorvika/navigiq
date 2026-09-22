/** What a change did to a plan: kept constraints, removed, added, cost delta. */
import { ArrowRight, Minus, Plus, RefreshCw } from "lucide-react";
import type { Comparison } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { rupees, signedRupees } from "@/lib/format";

export function ChangeSummary({ comparison, summary, className, title = "What changed" }: {
  comparison: Comparison | null | undefined; summary?: string[] | null; className?: string; title?: string;
}) {
  if (!comparison) return null;
  const { added, removed, retimed, estimated_cost: cost, changed_days: days } = comparison;
  const nothing = !added.length && !removed.length && !retimed.length;
  return (
    <section aria-label={title} className={cn("rounded-2xl bg-surface/70 p-4 ring-1 ring-border/60", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {days && days.length > 0 && (
          <p className="text-xs text-muted-foreground">Only day{days.length > 1 ? "s" : ""} {days.join(", ")} changed</p>
        )}
      </div>
      {summary && summary.length > 0 && (
        <p className="mt-1 text-sm text-muted-foreground">{summary.join(" · ")}</p>
      )}
      {nothing ? (
        <p className="mt-2 text-sm text-muted-foreground">The same places still fit best; timings and costs were re-checked.</p>
      ) : (
        <ul className="mt-3 space-y-1.5 text-sm">
          {removed.map((n) => (
            <li key={`r-${n}`} className="flex items-center gap-2">
              <span className="grid size-5 place-items-center rounded-full bg-danger-soft text-danger"><Minus className="size-3" aria-hidden="true" /></span>
              <span><span className="sr-only">Removed: </span><span className="line-through decoration-danger/50">{n}</span></span>
            </li>
          ))}
          {added.map((n) => (
            <li key={`a-${n}`} className="flex items-center gap-2">
              <span className="grid size-5 place-items-center rounded-full bg-success-soft text-success"><Plus className="size-3" aria-hidden="true" /></span>
              <span><span className="sr-only">Added: </span>{n}</span>
            </li>
          ))}
          {retimed.length > 0 && (
            <li className="flex items-center gap-2 text-muted-foreground">
              <span className="grid size-5 place-items-center rounded-full bg-info-soft text-info"><RefreshCw className="size-3" aria-hidden="true" /></span>
              New times for {retimed.join(", ")}
            </li>
          )}
        </ul>
      )}
      <p className="mt-3 flex flex-wrap items-center gap-1.5 text-sm">
        <span className="text-muted-foreground">Estimated cost</span>
        <span className="font-semibold">{rupees(cost.current)}</span>
        <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden="true" />
        <span className="font-semibold">{rupees(cost.variant)}</span>
        <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", cost.delta < 0 ? "bg-success-soft text-success" : cost.delta > 0 ? "bg-warning-soft text-warning" : "bg-surface text-muted-foreground")}>
          {signedRupees(cost.delta)}
        </span>
      </p>
    </section>
  );
}
