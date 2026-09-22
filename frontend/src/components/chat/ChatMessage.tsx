/**
 * Renders one assistant response by its `ui.type`. Text is the server's; all
 * facts in cards come from the structured `data` the deterministic services
 * returned. Citations link to the sources the answer was checked against.
 */
import { Link, useNavigate } from "@tanstack/react-router";
import { AlertTriangle, ArrowRight, BookOpen, Check, ExternalLink, Info, Map as MapIcon, Scale } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { AssistantResponse, Citation, Comparison, Itinerary, PoiDetail, ScoredPoi, Suggestion } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { costLabel, durationLabel } from "@/lib/format";
import { CategoryBadge, PoiRowCard, whereLabel } from "@/components/poi/PoiCard";
import { PoiArt } from "@/components/poi/PoiArt";
import { SaveButton } from "@/components/poi/SaveButton";
import { ChangeSummary } from "@/components/plan/ChangeSummary";
import { ItineraryPreview } from "@/components/plan/ItineraryPreview";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/primitives";

/** Text with [n] citation markers turned into links to the numbered sources. */
export function CitedText({ text, sources, idPrefix }: { text: string; sources: Citation[]; idPrefix: string }) {
  const known = new Set(sources.map((s) => s.n));
  const parts = text.split(/(\[\d+\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const m = /^\[(\d+)\]$/.exec(part);
        if (m && known.has(Number(m[1]))) {
          return (
            <sup key={i} className="ml-0.5">
              <a href={`#${idPrefix}-src-${m[1]}`} className="rounded px-0.5 text-xs font-semibold text-primary hover:underline" aria-label={`Source ${m[1]}`}>
                [{m[1]}]
              </a>
            </sup>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

function Sources({ sources, idPrefix }: { sources: Citation[]; idPrefix: string }) {
  if (!sources.length) return null;
  return (
    <div className="mt-3 rounded-2xl bg-surface/70 p-3.5">
      <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        <BookOpen className="size-3.5" aria-hidden="true" /> Sources
      </p>
      <ol className="space-y-2">
        {sources.map((s) => (
          <li key={s.n} id={`${idPrefix}-src-${s.n}`} className="flex gap-2 text-sm">
            <span className="font-semibold text-primary">[{s.n}]</span>
            <div className="min-w-0">
              {s.url ? (
                <a href={s.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium hover:underline">
                  {s.title}{s.section && s.section !== "Summary" ? ` — ${s.section}` : ""}
                  <ExternalLink className="size-3" aria-hidden="true" />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              ) : (
                <span className="font-medium">{s.title}</span>
              )}
              {s.license && <span className="ml-1.5 text-xs text-muted-foreground">{s.license}</span>}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Suggestions({ items, onPick, disabled, emphasis }: { items: Suggestion[]; onPick: (m: string) => void; disabled?: boolean; emphasis?: boolean }) {
  if (!items.length) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2" aria-label="Suggested replies">
      {items.map((s) => (
        <Chip key={s.label + s.message} onClick={() => onPick(s.message)} disabled={disabled} tone={emphasis ? "accent" : "default"} className="h-9">
          {s.label}
        </Chip>
      ))}
    </div>
  );
}

function PlaceList({ items, onShowMap }: { items: ScoredPoi[]; onShowMap?: () => void }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, 4);
  return (
    <div className="mt-3 space-y-2.5">
      <ul className="space-y-2.5">
        {shown.map((p) => <li key={p.id}><PoiRowCard poi={p} /></li>)}
      </ul>
      <div className="flex flex-wrap gap-2">
        {items.length > 4 && (
          <Button variant="ghost" size="sm" onClick={() => setAll((v) => !v)}>
            {all ? "Show fewer" : `Show all ${items.length}`}
          </Button>
        )}
        {onShowMap && (
          <Button variant="ghost" size="sm" onClick={onShowMap}><MapIcon aria-hidden="true" /> On the map</Button>
        )}
      </div>
    </div>
  );
}

function PlaceSummary({ poi, highlights, sources, idPrefix }: {
  poi: PoiDetail; highlights: { text: string; source_n: number }[]; sources: Citation[]; idPrefix: string;
}) {
  const navigate = useNavigate();
  return (
    <article className="mt-3 overflow-hidden rounded-3xl bg-card shadow-soft ring-1 ring-border/60">
      <div className="grid sm:grid-cols-[13rem_1fr]">
        <PoiArt poi={poi} className="h-40 w-full sm:h-full" />
        <div className="p-4">
          <CategoryBadge category={poi.category} />
          <h3 className="mt-2 font-display text-lg font-semibold">{poi.name}</h3>
          <p className="text-sm text-muted-foreground">{whereLabel(poi)}</p>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
            <div><dt className="text-xs text-muted-foreground">Cost per person</dt><dd className="font-semibold">{costLabel(poi.estimated_cost)} <span className="font-normal text-muted-foreground">est.</span></dd></div>
            <div><dt className="text-xs text-muted-foreground">Typical visit</dt><dd className="font-semibold">{durationLabel(poi.visit_duration)}</dd></div>
          </dl>
          {highlights.length > 0 && (
            <ul className="mt-3 space-y-1.5 text-sm text-foreground/85">
              {highlights.map((h, i) => (
                <li key={i} className="line-clamp-3">
                  {h.text}
                  {sources.some((s) => s.n === h.source_n) && (
                    <sup className="ml-0.5"><a href={`#${idPrefix}-src-${h.source_n}`} className="text-xs font-semibold text-primary">[{h.source_n}]</a></sup>
                  )}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button asChild size="sm"><Link to="/places/$placeId" params={{ placeId: String(poi.id) }}>Details <ArrowRight aria-hidden="true" /></Link></Button>
            <Button size="sm" variant="secondary" onClick={() => void navigate({ to: "/plans/new", search: { include: poi.id } })}>Plan around it</Button>
            <SaveButton poi={poi} variant="pill" className="h-9 px-4" />
          </div>
        </div>
      </div>
    </article>
  );
}

function ComparisonTable({ places, rows, ranking, aspect }: {
  places: PoiDetail[]; rows: { label: string; values: string[] }[]; ranking?: { id: number }[]; aspect?: string | null;
}) {
  const winner = aspect && ranking?.[0] ? ranking[0].id : null;
  return (
    <div className="mt-3 overflow-x-auto rounded-2xl ring-1 ring-border/70">
      <table className="w-full min-w-[32rem] border-collapse bg-card text-sm">
        <caption className="sr-only">Side-by-side comparison</caption>
        <thead>
          <tr className="bg-sand-50">
            <th scope="col" className="w-36 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <Scale className="mr-1 inline size-3.5" aria-hidden="true" />Compare
            </th>
            {places.map((p) => (
              <th key={p.id} scope="col" className="px-4 py-3 text-left">
                <Link to="/places/$placeId" params={{ placeId: String(p.id) }} className="font-display font-semibold hover:underline">{p.name}</Link>
                {winner === p.id && <span className="ml-2 rounded-full bg-success-soft px-2 py-0.5 text-[11px] font-semibold text-success">Better for {aspect}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-t border-border/60">
              <th scope="row" className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">{r.label}</th>
              {r.values.map((v, i) => <td key={i} className="px-4 py-2.5 align-top">{v}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WhatIfCard({ current, variant, comparison, change, onPick, disabled }: {
  current: Itinerary; variant: Itinerary; comparison: Comparison; change?: string[]; onPick: (m: string) => void; disabled?: boolean;
}) {
  return (
    <div className="mt-3 space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Current plan</p>
          <ItineraryPreview it={current} maxStops={5} />
        </div>
        <div>
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-accent">What if…</p>
          <ItineraryPreview it={{ ...variant, itinerary_id: undefined }} maxStops={5} className="ring-2 ring-accent/40" />
        </div>
      </div>
      <ChangeSummary comparison={comparison} summary={change} />
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => onPick("Keep my current plan")} disabled={disabled}>Keep current</Button>
        <Button variant="accent" onClick={() => onPick("Apply the what-if")} disabled={disabled}><Check aria-hidden="true" /> Apply this version</Button>
      </div>
    </div>
  );
}

function Notice({ tone, children }: { tone: "info" | "warning"; children: ReactNode }) {
  return (
    <p className={cn("mt-2 flex items-start gap-2 rounded-xl px-3 py-2 text-[13px]", tone === "info" ? "bg-info-soft text-info" : "bg-warning-soft text-warning")}>
      {tone === "info" ? <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" /> : <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />}
      <span>{children}</span>
    </p>
  );
}

export function AssistantMessage({ r, onPick, busy, idPrefix, onShowMap }: {
  r: AssistantResponse; onPick: (m: string) => void; busy?: boolean; idPrefix: string; onShowMap?: (items: ScoredPoi[]) => void;
}) {
  const d = r.data as Record<string, unknown>;
  const type = r.ui.type;
  const items = (d.items as ScoredPoi[] | undefined) ?? [];
  const suggestionsEmphasis = type === "clarification" || Boolean(d.mood_prompt);

  let body: ReactNode = null;
  if ((type === "discovery" || type === "poi_list") && items.length) {
    body = <PlaceList items={items} onShowMap={onShowMap ? () => onShowMap(items) : undefined} />;
  } else if (type === "poi_details" && d.poi) {
    body = <PlaceSummary poi={d.poi as PoiDetail} highlights={(d.highlights as { text: string; source_n: number }[]) ?? []} sources={r.sources} idPrefix={idPrefix} />;
  } else if (type === "comparison" && Array.isArray(d.places)) {
    body = <ComparisonTable places={d.places as PoiDetail[]} rows={(d.rows as { label: string; values: string[] }[]) ?? []} ranking={d.ranking as { id: number }[]} aspect={d.aspect as string | null} />;
  } else if (type === "itinerary" && d.itinerary) {
    const change = d.change as string[] | undefined;
    body = (
      <div className="mt-3 space-y-3">
        {d.comparison ? <ChangeSummary comparison={d.comparison as Comparison} summary={change} /> : null}
        <ItineraryPreview it={d.itinerary as Itinerary} />
      </div>
    );
  } else if (type === "itinerary_comparison" && d.current && d.variant && d.comparison) {
    body = <WhatIfCard current={d.current as Itinerary} variant={d.variant as Itinerary} comparison={d.comparison as Comparison} change={d.change as string[]} onPick={onPick} disabled={busy} />;
  } else if (type === "feasibility_error") {
    const feas = d.feasibility as { suggested_relaxations?: { description: string }[] } | undefined;
    body = feas?.suggested_relaxations?.length ? (
      <p className="mt-2 text-sm text-muted-foreground">Any of these would make it work:</p>
    ) : null;
  }

  const showSources = r.sources.length > 0 && (type === "knowledge_answer" || type === "poi_details");
  return (
    <div className="min-w-0">
      <div className={cn("text-[15px] leading-relaxed", type === "error" && "text-danger")}>
        {type === "knowledge_answer" ? <CitedText text={r.text} sources={r.sources} idPrefix={idPrefix} /> : r.text}
      </div>
      {body}
      {showSources && <Sources sources={r.sources} idPrefix={idPrefix} />}
      {r.warnings.map((w) => <Notice key={w} tone="warning">{w}</Notice>)}
      <Suggestions items={r.suggestions} onPick={onPick} disabled={busy} emphasis={suggestionsEmphasis} />
    </div>
  );
}
