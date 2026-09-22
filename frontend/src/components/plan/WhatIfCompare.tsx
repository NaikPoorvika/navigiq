/**
 * Side-by-side comparison of the current plan and a what-if variant. The
 * current plan stays untouched until the person applies the variant.
 */
import { Check, Plus } from "lucide-react";
import { useState } from "react";
import type { Comparison, Itinerary } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { clock, costLabel, dateLabel, plural } from "@/lib/format";
import { daysOf, isTrip, localSeq } from "@/lib/plan";
import { ChangeSummary } from "@/components/plan/ChangeSummary";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/primitives";

function Column({ it, other, heading, tone }: { it: Itinerary; other: Itinerary; heading: string; tone: "current" | "variant" }) {
  const otherIds = new Set(other.stops.map((s) => s.poi.id));
  const trip = isTrip(it);
  return (
    <div className={cn("rounded-3xl p-4", tone === "variant" ? "bg-accent-soft/50 ring-2 ring-accent/30" : "bg-sand-50 ring-1 ring-border/70")}>
      <p className={cn("text-xs font-semibold uppercase tracking-[0.12em]", tone === "variant" ? "text-clay-700" : "text-muted-foreground")}>{heading}</p>
      <p className="mt-1 text-sm">
        <span className="font-semibold">{costLabel(it.summary.estimated_cost)}</span>
        <span className="text-muted-foreground"> est. · {plural(it.summary.stop_count, "stop")}</span>
      </p>
      <div className="mt-3 space-y-3">
        {daysOf(it).map((d) => (
          <div key={d.day}>
            {trip && <p className="mb-1.5 text-xs font-semibold text-muted-foreground">Day {d.day} · {dateLabel(d.date)}</p>}
            <ol className="space-y-1.5">
              {d.stops.map((s) => {
                const unique = !otherIds.has(s.poi.id);
                return (
                  <li key={s.seq} className={cn("flex items-center gap-2.5 rounded-xl px-2 py-1.5 text-sm", unique && (tone === "variant" ? "bg-success-soft/80" : "bg-danger-soft/70"))}>
                    <span className="grid size-6 shrink-0 place-items-center rounded-full bg-card text-[11px] font-semibold ring-1 ring-border">{localSeq(s)}</span>
                    <span className="w-14 shrink-0 tabular-nums text-xs text-muted-foreground">{clock(s.arrive)}</span>
                    <span className={cn("min-w-0 truncate", unique && tone === "current" && "line-through decoration-danger/50")}>{s.poi.name}</span>
                    {unique && tone === "variant" && <Plus className="ml-auto size-3.5 shrink-0 text-success" aria-label="new" />}
                  </li>
                );
              })}
            </ol>
          </div>
        ))}
      </div>
    </div>
  );
}

export function WhatIfCompare({ current, variant, comparison, summary, onKeep, onApply, busy }: {
  current: Itinerary; variant: Itinerary; comparison: Comparison; summary: string[];
  onKeep: () => void; onApply: () => void; busy?: "keep" | "apply" | null;
}) {
  const [tab, setTab] = useState<"current" | "variant">("variant");
  return (
    <div className="space-y-4">
      <ChangeSummary comparison={comparison} summary={summary} title="If you apply this" />
      <div className="md:hidden">
        <Segmented label="Show" value={tab} onChange={setTab} options={[{ value: "current", label: "Current" }, { value: "variant", label: "What if" }]} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div className={cn(tab === "variant" && "hidden md:block")}><Column it={current} other={variant} heading="Current plan" tone="current" /></div>
        <div className={cn(tab === "current" && "hidden md:block")}><Column it={variant} other={current} heading="What if" tone="variant" /></div>
      </div>
      <div className="flex flex-wrap justify-end gap-2 pt-1">
        <Button variant="secondary" onClick={onKeep} loading={busy === "keep"} disabled={Boolean(busy)}>Keep current</Button>
        <Button variant="accent" onClick={onApply} loading={busy === "apply"} disabled={Boolean(busy)}><Check aria-hidden="true" /> Apply what-if</Button>
      </div>
    </div>
  );
}
