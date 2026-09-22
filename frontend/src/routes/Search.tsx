/**
 * Explore all places: filters over the real catalogue, with a map view.
 * Text search and filters hit /pois (deterministic search); a mood alone
 * uses the recommendation engine, so the cards can say why.
 */
import { useNavigate, useSearch } from "@tanstack/react-router";
import { ListFilter, MapPin, Search as SearchIcon, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { PageFooter } from "@/components/layout/AppShell";
import { LazyMap } from "@/components/map/LazyMap";
import { PoiGrid } from "@/components/poi/PoiRail";
import { PoiRowCard } from "@/components/poi/PoiCard";
import { Button } from "@/components/ui/button";
import { ResponsivePanel } from "@/components/ui/overlay";
import { Badge, Chip, EmptyState, ErrorState, Input, Segmented } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import type { PoiCard, ScoredPoi } from "@/lib/api/types";
import { EXPLORE_CATEGORIES, MOODS, categoryMeta } from "@/lib/categories";
import { cn } from "@/lib/cn";
import { rupees } from "@/lib/format";
import { useDebounced, useDocumentTitle, useIsDesktop } from "@/lib/hooks";
import { usePois, useRecommend } from "@/lib/queries";

const BUDGETS = [200, 500, 1000, 2000] as const;
const SCOPES = [
  { value: "city" as const, label: "In the city" },
  { value: "regional" as const, label: "Day trips" },
  { value: "anywhere" as const, label: "Anywhere" },
];

export function SearchPage() {
  useDocumentTitle("Explore places");
  const search = useSearch({ from: "/search" });
  const navigate = useNavigate();
  const desktop = useIsDesktop();
  const [text, setText] = useState(search.q ?? "");
  const [areaText, setAreaText] = useState(search.area ?? "");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const q = useDebounced(text.trim(), 350);
  const area = useDebounced(areaText.trim(), 450);

  const set = (patch: Partial<typeof search>) =>
    void navigate({ to: "/search", search: (old) => ({ ...old, ...patch }), replace: true });

  useEffect(() => {
    if ((search.q ?? "") !== q) set({ q: q || undefined });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);
  useEffect(() => {
    if ((search.area ?? "") !== area) set({ area: area || undefined });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [area]);

  const categories = search.category ?? [];
  const moodOnly = Boolean(search.mood && !q && !categories.length && !area);
  const filterCount = categories.length + (search.mood ? 1 : 0) + (area ? 1 : 0) + (search.max_cost ? 1 : 0) + (search.scope ? 1 : 0);

  const list = usePois(
    { q: q || undefined, category: categories.length ? categories : undefined, area: area || undefined, scope: search.scope, max_cost: search.max_cost, limit: 36 },
    !moodOnly,
  );
  const recommended = useRecommend(
    { moods: search.mood ? [search.mood] : [], scope: search.scope ?? "city", budget_per_person: search.max_cost, limit: 20 },
    moodOnly,
  );

  const items: (PoiCard | ScoredPoi)[] = useMemo(
    () => (moodOnly ? recommended.data?.items ?? [] : list.data?.items ?? []),
    [moodOnly, recommended.data, list.data],
  );
  const pending = moodOnly ? recommended.isPending : list.isPending;
  const error = moodOnly ? recommended.error : list.error;
  const areaMissing = error instanceof ApiError && error.code === "AREA_NOT_FOUND";
  const resolvedArea = list.data?.area;
  const pins = useMemo(() => items.map((p) => ({ id: p.id, lat: p.lat, lon: p.lon, title: p.name })), [items]);
  const view = search.view === "map" ? "map" : "list";

  const toggleCategory = (key: string) => {
    const next = categories.includes(key) ? categories.filter((c) => c !== key) : [...categories, key];
    set({ category: next.length ? next : undefined });
  };

  const clearAll = () => {
    setText("");
    setAreaText("");
    void navigate({ to: "/search", search: {}, replace: true });
  };

  const filters = (
    <div className="space-y-5">
      <div>
        <p className="mb-2 text-sm font-semibold">Kind of place</p>
        <div className="flex flex-wrap gap-2">
          {EXPLORE_CATEGORIES.map((c) => (
            <Chip key={c} selected={categories.includes(c)} onClick={() => toggleCategory(c)} className="h-9">
              {categoryMeta(c).label}
            </Chip>
          ))}
        </div>
      </div>
      <div>
        <p className="mb-2 text-sm font-semibold">Mood</p>
        <div className="flex flex-wrap gap-2">
          {MOODS.map((m) => (
            <Chip key={m.key} selected={search.mood === m.key} onClick={() => set({ mood: search.mood === m.key ? undefined : m.key })} className="h-9">
              {m.label}
            </Chip>
          ))}
        </div>
      </div>
      <div>
        <label htmlFor="area-input" className="mb-2 block text-sm font-semibold">Around an area</label>
        <Input
          id="area-input"
          value={areaText}
          onChange={(e) => setAreaText(e.target.value)}
          placeholder="Indiranagar, Jayanagar, Whitefield…"
          aria-describedby="area-hint"
        />
        <p id="area-hint" className="mt-1 text-xs text-muted-foreground">
          {resolvedArea ? `Showing places within a few km of ${resolvedArea.name}.` : "Areas come from NavigIQ's gazetteer; unknown names are reported, never guessed."}
        </p>
      </div>
      <div>
        <p className="mb-2 text-sm font-semibold">Budget per person</p>
        <div className="flex flex-wrap gap-2">
          {BUDGETS.map((b) => (
            <Chip key={b} selected={search.max_cost === b} onClick={() => set({ max_cost: search.max_cost === b ? undefined : b })} className="h-9">
              Under {rupees(b)}
            </Chip>
          ))}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">Costs are NavigIQ's estimates, not live prices.</p>
      </div>
      <div>
        <p className="mb-2 text-sm font-semibold">How far</p>
        <Segmented label="How far" value={search.scope ?? "city"} onChange={(v) => set({ scope: v === "city" ? undefined : v })} options={SCOPES} />
      </div>
    </div>
  );

  return (
    <>
      <main id="main" className="mx-auto max-w-page px-4 pb-10 pt-6 sm:px-6 lg:px-8">
        <h1 className="font-display text-3xl font-semibold tracking-tight">Explore places</h1>
        <p className="mt-1.5 text-muted-foreground">
          {`Bengaluru and up to 90 km around it. `}
          <span className="text-foreground/70">Cards show NavigIQ's cost and time estimates — never invented ratings.</span>
        </p>

        <div className="sticky top-16 z-20 -mx-4 mt-5 bg-background/90 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <SearchIcon className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <label htmlFor="q" className="sr-only">Search places by name</label>
              <Input id="q" value={text} onChange={(e) => setText(e.target.value)} placeholder="Search by name or what it is…" className="pl-11" type="search" />
            </div>
            <Button variant={filterCount ? "primary" : "outline"} onClick={() => setFiltersOpen(true)} className="lg:hidden">
              <ListFilter aria-hidden="true" /> Filters{filterCount ? ` (${filterCount})` : ""}
            </Button>
            <Segmented
              label="View"
              value={view}
              onChange={(v) => set({ view: v === "map" ? "map" : undefined })}
              options={[{ value: "list", label: "List" }, { value: "map", label: "Map" }]}
              className="hidden sm:inline-flex"
            />
          </div>
          <div className="mt-2 sm:hidden">
            <Segmented
              label="View"
              value={view}
              onChange={(v) => set({ view: v === "map" ? "map" : undefined })}
              options={[{ value: "list", label: "List" }, { value: "map", label: "Map" }]}
            />
          </div>
          {filterCount > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {categories.map((c) => (
                <Badge key={c} tone="primary" className="gap-1.5 pr-1.5">
                  {categoryMeta(c).label}
                  <button type="button" onClick={() => toggleCategory(c)} aria-label={`Remove ${categoryMeta(c).label} filter`} className="grid size-4 place-items-center rounded-full hover:bg-primary/15">
                    <X className="size-3" aria-hidden="true" />
                  </button>
                </Badge>
              ))}
              {search.mood && <Badge tone="primary">{MOODS.find((m) => m.key === search.mood)?.label ?? search.mood}</Badge>}
              {area && <Badge tone="primary"><MapPin aria-hidden="true" /> {area}</Badge>}
              {search.max_cost && <Badge tone="primary">Under {rupees(search.max_cost)}</Badge>}
              {search.scope && <Badge tone="primary">{SCOPES.find((s) => s.value === search.scope)?.label}</Badge>}
              <Button variant="link" size="sm" onClick={clearAll} className="h-7">Clear all</Button>
            </div>
          )}
        </div>

        <div className="mt-6 grid gap-8 lg:grid-cols-[17rem_minmax(0,1fr)]">
          <aside className="hidden lg:block" aria-label="Filters">
            <div className="sticky top-36 rounded-3xl bg-card p-5 ring-1 ring-border/60">{filters}</div>
          </aside>

          <div>
            {areaMissing ? (
              <EmptyState
                icon={<MapPin aria-hidden="true" />}
                title={`We couldn't find “${area}” on the map`}
                description="NavigIQ only uses areas it can place exactly, so it won't guess. Try a nearby locality, or search without an area."
                action={<Button onClick={() => setAreaText("")}>Clear the area</Button>}
              />
            ) : error ? (
              <ErrorState description="The search didn't come back." onRetry={() => void (moodOnly ? recommended.refetch() : list.refetch())} />
            ) : view === "map" && desktop ? (
              <div className="grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
                <ul className="max-h-[70vh] space-y-2.5 overflow-y-auto pr-1">
                  {items.map((p) => (
                    <li key={p.id}>
                      <PoiRowCard poi={p} selected={selected === p.id} onSelect={() => setSelected(p.id)} />
                    </li>
                  ))}
                </ul>
                <LazyMap label="Map of search results" className="sticky top-36 h-[70vh] overflow-hidden rounded-3xl ring-1 ring-border" pins={pins} selectedId={selected} onSelect={(id) => setSelected(Number(id))} />
              </div>
            ) : view === "map" ? (
              <LazyMap label="Map of search results" className="h-[65dvh] overflow-hidden rounded-3xl ring-1 ring-border" pins={pins} selectedId={selected} onSelect={(id) => setSelected(Number(id))} />
            ) : pending ? (
              <PoiGrid items={[]} loading count={6} />
            ) : items.length === 0 ? (
              <EmptyState
                icon={<SearchIcon aria-hidden="true" />}
                title="Nothing matched all of that"
                description="NavigIQ would rather show nothing than pad the list with places that don't fit. Try removing a filter, widening the distance, or asking in your own words."
                action={
                  <>
                    {filterCount > 0 && <Button variant="secondary" onClick={clearAll}>Clear filters</Button>}
                    <Button onClick={() => void navigate({ to: "/ask", search: { q: text || "What should I do in Bengaluru today?", new: true } })}>
                      <Sparkles aria-hidden="true" /> Ask NavigIQ instead
                    </Button>
                  </>
                }
              />
            ) : (
              <>
                <p className="mb-4 text-sm text-muted-foreground" role="status">
                  {items.length} place{items.length === 1 ? "" : "s"}
                  {resolvedArea ? ` near ${resolvedArea.name}` : ""}
                  {moodOnly ? " · ranked for that mood, with reasons" : ""}
                </p>
                <PoiGrid items={items} />
              </>
            )}
          </div>
        </div>
      </main>
      <PageFooter />

      <ResponsivePanel open={filtersOpen} onOpenChange={setFiltersOpen} title="Filters" description="Narrow the catalogue."
        footer={
          <div className="flex justify-between gap-2">
            <Button variant="ghost" onClick={clearAll}>Clear all</Button>
            <Button onClick={() => setFiltersOpen(false)}>Show {items.length} results</Button>
          </div>
        }>
        <div className={cn("pb-2")}>{filters}</div>
      </ResponsivePanel>
    </>
  );
}
