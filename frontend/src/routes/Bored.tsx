/**
 * "I'm bored" — the serendipity screen. Moods and surprises come from the
 * recommendation engine (with its novelty rules), so a second look really is
 * different rather than a reshuffle of the same list.
 */
import { useMutation } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowRight, CloudRain, Dices, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { PageFooter } from "@/components/layout/AppShell";
import { CategoryArt, PoiArt } from "@/components/poi/PoiArt";
import { PoiGrid } from "@/components/poi/PoiRail";
import { SaveButton } from "@/components/poi/SaveButton";
import { CategoryBadge, whereLabel } from "@/components/poi/PoiCard";
import { Button } from "@/components/ui/button";
import { Badge, ErrorState, SectionHeader, Skeleton, WorkingNote } from "@/components/ui/primitives";
import { endpoints } from "@/lib/api/endpoints";
import type { ScoredPoi } from "@/lib/api/types";
import { GROUP_TONE, type CategoryGroup } from "@/lib/categories";
import { cn } from "@/lib/cn";
import { costLabel, durationLabel } from "@/lib/format";
import { useDocumentTitle } from "@/lib/hooks";
import { useHomeContext, useRecommend } from "@/lib/queries";

const MOOD_TILES: { mood: string; label: string; blurb: string; art: string; group: CategoryGroup }[] = [
  { mood: "peaceful", label: "Somewhere calm", blurb: "Quiet corners, gardens, lakes", art: "park", group: "nature" },
  { mood: "adventurous", label: "Do something", blurb: "Active, outdoorsy, a bit of effort", art: "adventure", group: "fun" },
  { mood: "foodie", label: "Eat well", blurb: "Local food, cafés, sweets", art: "street_food", group: "food" },
  { mood: "cultural", label: "Learn something", blurb: "Museums, galleries, heritage", art: "museum", group: "culture" },
  { mood: "social", label: "With people", blurb: "Lively, group-friendly spots", art: "nightlife", group: "fun" },
  { mood: "creative", label: "Make something", blurb: "Workshops, studios, hands-on", art: "workshop", group: "experience" },
  { mood: "photography", label: "Photogenic", blurb: "Places that look good", art: "viewpoint", group: "nature" },
  { mood: "budget", label: "Spend nothing", blurb: "Free or nearly free", art: "market", group: "shopping" },
];

function Spotlight({ poi, onDifferent, busy }: { poi: ScoredPoi; onDifferent: () => void; busy: boolean }) {
  const navigate = useNavigate();
  return (
    <article className="animate-pop overflow-hidden rounded-[2rem] bg-card shadow-lift ring-1 ring-border/60">
      <div className="grid md:grid-cols-2">
        <PoiArt poi={poi} className="h-56 w-full md:h-full" iconSize="lg" />
        <div className="p-6">
          <div className="flex flex-wrap items-center gap-2">
            <CategoryBadge category={poi.category} />
            {poi.estimated_cost.max === 0 && <Badge tone="success">Free</Badge>}
            {poi.day_trip_suitable && <Badge tone="info">Day trip</Badge>}
          </div>
          <h3 className="mt-3 font-display text-2xl font-semibold tracking-tight">{poi.name}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{whereLabel(poi)}</p>
          {poi.short_description && <p className="mt-3 text-foreground/85">{poi.short_description}</p>}
          {poi.why.length > 0 && (
            <p className="mt-3 flex items-start gap-2 text-sm text-primary">
              <Sparkles className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span><span className="sr-only">Why NavigIQ picked it: </span>{poi.why.join(" · ")}</span>
            </p>
          )}
          <p className="mt-3 text-sm text-muted-foreground">
            <span className="font-semibold text-foreground">{costLabel(poi.estimated_cost)}</span> per person est. · about {durationLabel(poi.visit_duration)}
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button onClick={onDifferent} loading={busy} variant="accent">
              <RefreshCw aria-hidden="true" /> Show me something different
            </Button>
            <SaveButton poi={poi} variant="pill" className="h-11" />
            <Button variant="secondary" onClick={() => void navigate({ to: "/places/$placeId", params: { placeId: String(poi.id) } })}>
              Details <ArrowRight aria-hidden="true" />
            </Button>
          </div>
        </div>
      </div>
    </article>
  );
}

export function BoredPage() {
  useDocumentTitle("I'm bored");
  const { surprise: autoSurprise } = useSearch({ from: "/bored" });
  const ctx = useHomeContext();
  const rain = Boolean(ctx.data?.weather.available && (ctx.data.weather.rain_likely || ctx.data.weather.heavy_rain_expected));
  const [mood, setMood] = useState<string | null>(null);
  const [seen, setSeen] = useState<number[]>([]);
  const [pick, setPick] = useState<ScoredPoi | null>(null);
  const started = useRef(false);

  const surprise = useMutation({
    mutationFn: (exclude: number[]) =>
      endpoints.surprise({ exclude_ids: exclude.slice(-40), limit: 3, indoor_preference: rain ? "indoor" : undefined }),
    onSuccess: (res) => {
      const next = res.items[0];
      if (next) {
        setPick(next);
        setSeen((s) => [...s, next.id]);
      }
    },
  });

  useEffect(() => {
    if (autoSurprise && !started.current) {
      started.current = true;
      surprise.mutate([]);
    }
  }, [autoSurprise, surprise]);

  const moodResults = useRecommend(
    { moods: mood ? [mood] : [], mode: "discover", indoor_preference: rain ? "indoor" : undefined, rain_expected: rain || undefined, limit: 9 },
    Boolean(mood),
  );

  return (
    <>
      <main id="main" className="mx-auto max-w-page px-4 pb-12 pt-8 sm:px-6 lg:px-8">
        <header className="max-w-2xl">
          <p className="inline-flex items-center gap-2 rounded-full bg-accent-soft px-3 py-1 text-sm font-semibold text-clay-700">
            <Dices className="size-4" aria-hidden="true" /> I'm bored
          </p>
          <h1 className="mt-3 font-display text-4xl font-semibold tracking-tight sm:text-5xl">Let's fix that.</h1>
          <p className="mt-3 text-lg text-muted-foreground">
            Pick a mood, or let NavigIQ throw something at you. Every suggestion is a real place with real opening hours and a cost estimate.
          </p>
          {rain && (
            <p className="mt-3 inline-flex items-center gap-2 rounded-full bg-info-soft px-3 py-1.5 text-sm text-info">
              <CloudRain className="size-4" aria-hidden="true" /> Rain is likely today, so these lean indoors.
            </p>
          )}
        </header>

        <section className="mt-8" aria-labelledby="surprise-title">
          <SectionHeader id="surprise-title" title="Surprise me" description="One place at a time, from the parts of the catalogue you haven't seen." />
          {surprise.isPending && !pick ? (
            <div className="rounded-[2rem] bg-card p-6 ring-1 ring-border/60">
              <WorkingNote>Picking something you haven't seen…</WorkingNote>
              <Skeleton className="mt-4 h-40" />
            </div>
          ) : surprise.isError ? (
            <ErrorState description="The surprise didn't load." onRetry={() => surprise.mutate(seen)} />
          ) : pick ? (
            <Spotlight poi={pick} onDifferent={() => surprise.mutate(seen)} busy={surprise.isPending} />
          ) : (
            <div className="flex flex-col items-center gap-4 rounded-[2rem] border border-dashed border-border-strong bg-card/60 px-6 py-10 text-center">
              <div className="grid size-14 place-items-center rounded-2xl bg-accent-soft text-clay-700">
                <Dices className="size-7" aria-hidden="true" />
              </div>
              <p className="max-w-md text-muted-foreground">No filters, no scrolling — one idea at a time, and a button to reject it.</p>
              <Button variant="accent" size="lg" onClick={() => surprise.mutate([])} loading={surprise.isPending}>
                <Sparkles aria-hidden="true" /> Surprise me
              </Button>
            </div>
          )}
        </section>

        <section className="mt-12" aria-labelledby="moods-title">
          <SectionHeader id="moods-title" title="Or pick a mood" description="NavigIQ ranks places for the mood and says why each one fits." />
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {MOOD_TILES.map((t) => {
              const tone = GROUP_TONE[t.group];
              const active = mood === t.mood;
              return (
                <li key={t.mood}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => setMood(active ? null : t.mood)}
                    className={cn(
                      "group relative block h-36 w-full overflow-hidden rounded-3xl text-left ring-1 transition-[transform,box-shadow] hover:-translate-y-0.5 hover:shadow-lift sm:h-40",
                      active ? "ring-2 ring-primary" : "ring-border/50",
                    )}
                  >
                    <CategoryArt category={t.art} seed={t.mood} className={cn("absolute inset-0 size-full", tone.bg)} iconSize="lg" />
                    <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-card via-card/85 to-transparent p-3.5">
                      <span className="block font-display text-sm font-semibold sm:text-base">{t.label}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">{t.blurb}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>

        {mood && (
          <section className="mt-10" aria-live="polite">
            <SectionHeader
              title={`${MOOD_TILES.find((t) => t.mood === mood)?.label ?? "Ideas"} right now`}
              action={<Button variant="ghost" size="sm" onClick={() => void moodResults.refetch()}><RefreshCw aria-hidden="true" /> Refresh</Button>}
            />
            {moodResults.isError ? (
              <ErrorState description="Those ideas didn't load." onRetry={() => void moodResults.refetch()} />
            ) : (
              <PoiGrid items={moodResults.data?.items} loading={moodResults.isPending} />
            )}
          </section>
        )}
      </main>
      <PageFooter />
    </>
  );
}
