/**
 * The plan builder — the structured path that never needs the language model.
 * It sends a TripSpec to the same deterministic planner the assistant uses,
 * and shows a real preview (planned, validated, not saved) before you commit.
 */
import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { CalendarDays, CalendarPlus, Check, CircleAlert, Eye, MapPin, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PageFooter } from "@/components/layout/AppShell";
import { ItineraryPreview } from "@/components/plan/ItineraryPreview";
import { Button } from "@/components/ui/button";
import { Badge, Chip, ErrorState, Field, Input, SectionHeader, Segmented, WorkingNote } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { Feasibility, Itinerary, PoiDetail, Relaxation, TripSpec } from "@/lib/api/types";
import { EXPLORE_CATEGORIES, MOODS, categoryMeta } from "@/lib/categories";
import { cn } from "@/lib/cn";
import { addDays, dateLabel, plural, rupees, todayIST } from "@/lib/format";
import { useDocumentTitle, useElapsed } from "@/lib/hooks";
import { usePoi, usePreferences } from "@/lib/queries";

const WINDOWS = [
  { id: "morning", label: "Morning", start: "09:00", end: "13:00" },
  { id: "afternoon", label: "Afternoon", start: "12:00", end: "17:00" },
  { id: "fullday", label: "Full day", start: "10:00", end: "18:00" },
  { id: "evening", label: "Evening", start: "16:00", end: "21:00" },
];
const BUDGETS = [500, 1000, 2000, 4000];
const PARTY_TYPES = [
  { key: "solo", label: "On my own" },
  { key: "couple", label: "Couple" },
  { key: "friends", label: "Friends" },
  { key: "family_with_kids", label: "Family with kids" },
  { key: "parents", label: "With parents" },
  { key: "colleagues", label: "Colleagues" },
];
const MEALS = [
  { key: "breakfast", label: "Breakfast" },
  { key: "lunch", label: "Lunch" },
  { key: "coffee", label: "Coffee" },
  { key: "snacks", label: "Snacks" },
  { key: "dinner", label: "Dinner" },
];

interface Draft {
  date: string;
  days: number;
  start: string;
  end: string;
  partySize: number;
  partyType: string | null;
  budget: number | null;
  interests: string[];
  moods: string[];
  area: string;
  pace: "quick" | "balanced" | "relaxed";
  meals: string[];
  mustInclude: number[];
}

function toggle(list: string[], v: string): string[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

async function buildSpec(d: Draft): Promise<{ spec: Partial<TripSpec>; note: string | null }> {
  let anchor: TripSpec["anchor_area"] = null;
  let note: string | null = null;
  const area = d.area.trim();
  if (area) {
    const res = await api.get<{ resolved: boolean; area: { name: string; lat: number; lon: number; radius_km: number } | null }>(
      "/pois/resolve-area", { name: area });
    if (res.resolved && res.area) anchor = res.area as TripSpec["anchor_area"];
    else note = `We couldn't place “${area}” on the map, so the plan isn't limited to it.`;
  }
  return {
    spec: {
      date: d.date,
      end_date: d.days > 1 ? addDays(d.date, d.days - 1) : null,
      start_time: d.start,
      end_time: d.end,
      party_size: d.partySize,
      party_type: d.partyType,
      budget_total: d.budget,
      interests: [...d.interests, ...d.moods],
      pace: d.pace,
      meal_preferences: d.meals,
      must_include_poi_ids: d.mustInclude,
      ...(anchor ? { anchor_area: anchor } : {}),
    },
    note,
  };
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-3xl bg-card p-5 ring-1 ring-border/60">
      <h2 className="font-display text-lg font-semibold">{title}</h2>
      {hint && <p className="mt-1 text-sm text-muted-foreground">{hint}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function PlanNewPage() {
  useDocumentTitle("Build a plan");
  const search = useSearch({ from: "/plans/new" });
  const navigate = useNavigate();
  const prefs = usePreferences();
  const includePoi = usePoi(search.include ?? 0);
  const [draft, setDraft] = useState<Draft>(() => ({
    date: todayIST(),
    days: search.days && search.days > 1 ? Math.min(search.days, 7) : 1,
    start: "10:00",
    end: "18:00",
    partySize: 1,
    partyType: null,
    budget: null,
    interests: search.interests ?? [],
    moods: [],
    area: "",
    pace: "balanced",
    meals: [],
    mustInclude: search.include ? [search.include] : [],
  }));
  const [preview, setPreview] = useState<Itinerary | null>(null);
  const [problem, setProblem] = useState<{ message: string; relaxations: Relaxation[] } | null>(null);
  const [areaNote, setAreaNote] = useState<string | null>(null);
  const set = (patch: Partial<Draft>) => { setDraft((d) => ({ ...d, ...patch })); setPreview(null); setProblem(null); };

  const applyPrefs = () => {
    const p = prefs.data;
    if (!p) return;
    set({
      interests: [...new Set([...draft.interests, ...p.favorite_categories])].slice(0, 8),
      moods: [...new Set([...draft.moods, ...p.favorite_moods])].slice(0, 4),
      pace: p.preferred_pace ?? draft.pace,
      budget: draft.budget ?? p.typical_budget_inr,
    });
  };

  const handleFailure = (err: unknown) => {
    if (err instanceof ApiError) {
      if (err.code === "INFEASIBLE") {
        const feas = (err.details?.feasibility ?? {}) as Feasibility;
        setProblem({ message: feas.message ?? err.message, relaxations: feas.suggested_relaxations ?? [] });
        return;
      }
      if (err.code === "SEMANTIC_INVALID") {
        const errors = (err.details?.errors ?? []) as { message: string }[];
        setProblem({ message: errors.map((e) => e.message).join(". ") || err.message, relaxations: [] });
        return;
      }
      toast.error(err.message);
      return;
    }
    toast.error("The planner didn't respond. Try again.");
  };

  const previewRun = useMutation({
    mutationFn: async () => {
      const { spec, note } = await buildSpec(draft);
      setAreaNote(note);
      return api.post<{ itinerary: Itinerary }>("/plans/preview", spec as Record<string, unknown>);
    },
    onMutate: () => { setProblem(null); setPreview(null); },
    onSuccess: (res) => setPreview(res.itinerary),
    onError: handleFailure,
  });

  const create = useMutation({
    mutationFn: async () => {
      const { spec, note } = await buildSpec(draft);
      setAreaNote(note);
      return endpoints.createPlan(spec);
    },
    onMutate: () => setProblem(null),
    onSuccess: (res) => {
      if (res.itinerary?.itinerary_id) {
        toast.success("Plan ready");
        void navigate({ to: "/plans/$planId", params: { planId: String(res.itinerary.itinerary_id) } });
      }
    },
    onError: handleFailure,
  });

  const busy = previewRun.isPending || create.isPending;
  const elapsed = useElapsed(busy);
  const applyRelaxation = (r: Relaxation) => {
    const op = r.operation;
    if (op.op === "set_budget" && op.amount !== undefined) set({ budget: op.amount });
    else if (op.op === "set_end_time" && op.time) set({ end: op.time });
    else if (op.op === "set_pace" && op.pace) set({ pace: op.pace });
    else if (op.op === "set_area") set({ area: "" });
    else if (op.op === "remove_interest" && op.interest) set({ interests: draft.interests.filter((i) => i !== op.interest), moods: draft.moods.filter((m) => m !== op.interest) });
    else if (op.op === "add_interest" && op.interest) set({ moods: [...new Set([...draft.moods, op.interest])] });
    else if (op.op === "set_stop_count") toast("Ask for fewer stops by choosing a shorter window or a relaxed pace.");
    setProblem(null);
  };

  const dateChips = [
    { label: "Today", value: todayIST() },
    { label: "Tomorrow", value: addDays(todayIST(), 1) },
    { label: "This weekend", value: (() => { const t = todayIST(); for (let i = 0; i < 7; i++) { const d = addDays(t, i); if (new Date(`${d}T00:00:00Z`).getUTCDay() === 6) return d; } return t; })() },
  ];

  return (
    <>
      <main id="main" className="mx-auto max-w-page px-4 pb-12 pt-6 sm:px-6 lg:px-8">
        <SectionHeader
          eyebrow="Plan"
          title="Build a plan"
          description="No model needed for this path: NavigIQ's planner picks places, checks opening hours and keeps you inside your budget and time."
          action={<Button asChild variant="ghost" size="sm"><Link to="/ask" search={{ q: "Plan a day for me", new: true }}><Sparkles aria-hidden="true" /> Describe it instead</Link></Button>}
        />

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_23rem]">
          <div className="space-y-4">
            <Section title="When" hint="Trips can run up to seven days; each day is planned separately.">
              <div className="flex flex-wrap items-center gap-2">
                {dateChips.map((c) => (
                  <Chip key={c.label} className="h-9" selected={draft.date === c.value} onClick={() => set({ date: c.value })}>{c.label}</Chip>
                ))}
                <label htmlFor="date" className="sr-only">Start date</label>
                <Input id="date" type="date" value={draft.date} min={todayIST()} className="h-10 w-auto" onChange={(e) => set({ date: e.target.value })} />
              </div>
              <div className="mt-4">
                <p className="mb-2 text-sm font-semibold">How many days</p>
                <div className="flex flex-wrap gap-2">
                  {[1, 2, 3, 4, 5, 6, 7].map((n) => (
                    <Chip key={n} className="h-9 w-12 justify-center" selected={draft.days === n} onClick={() => set({ days: n })}>{n}</Chip>
                  ))}
                </div>
                {draft.days > 1 && (
                  <p className="mt-2 text-sm text-muted-foreground">
                    <CalendarDays className="mr-1 inline size-3.5 align-[-2px]" aria-hidden="true" />
                    {dateLabel(draft.date)} – {dateLabel(addDays(draft.date, draft.days - 1))} · no place repeats across days
                  </p>
                )}
              </div>
              <div className="mt-4">
                <p className="mb-2 text-sm font-semibold">Hours each day</p>
                <div className="flex flex-wrap gap-2">
                  {WINDOWS.map((w) => (
                    <Chip key={w.id} className="h-9" selected={draft.start === w.start && draft.end === w.end} onClick={() => set({ start: w.start, end: w.end })}>
                      {w.label}
                    </Chip>
                  ))}
                  <span className="inline-flex items-center gap-1.5">
                    <label htmlFor="start" className="sr-only">Start time</label>
                    <Input id="start" type="time" value={draft.start} className="h-10 w-auto" onChange={(e) => set({ start: e.target.value })} />
                    <span aria-hidden="true">–</span>
                    <label htmlFor="end" className="sr-only">End time</label>
                    <Input id="end" type="time" value={draft.end} className="h-10 w-auto" onChange={(e) => set({ end: e.target.value })} />
                  </span>
                </div>
              </div>
            </Section>

            <Section title="What you're in the mood for" hint="Pick a few — the planner covers each of them if it can.">
              <div className="flex flex-wrap gap-2">
                {EXPLORE_CATEGORIES.map((c) => (
                  <Chip key={c} className="h-9" selected={draft.interests.includes(c)} onClick={() => set({ interests: toggle(draft.interests, c) })}>
                    {categoryMeta(c).label}
                  </Chip>
                ))}
              </div>
              <p className="mb-2 mt-4 text-sm font-semibold">Moods</p>
              <div className="flex flex-wrap gap-2">
                {MOODS.map((m) => (
                  <Chip key={m.key} className="h-9" selected={draft.moods.includes(m.key)} onClick={() => set({ moods: toggle(draft.moods, m.key) })}>{m.label}</Chip>
                ))}
              </div>
              {prefs.data && (prefs.data.favorite_categories.length > 0 || prefs.data.favorite_moods.length > 0) && (
                <Button variant="link" size="sm" className="mt-3" onClick={applyPrefs}>Use my saved preferences</Button>
              )}
            </Section>

            <Section title="Who's going">
              <div className="flex flex-wrap items-center gap-4">
                <div className="flex items-center gap-2">
                  <Button variant="outline" size="icon-sm" aria-label="Fewer people" onClick={() => set({ partySize: Math.max(1, draft.partySize - 1) })}>−</Button>
                  <span className="min-w-20 text-center text-sm font-semibold">{plural(draft.partySize, "person", "people")}</span>
                  <Button variant="outline" size="icon-sm" aria-label="More people" onClick={() => set({ partySize: Math.min(20, draft.partySize + 1) })}>+</Button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {PARTY_TYPES.map((p) => (
                    <Chip key={p.key} className="h-9" selected={draft.partyType === p.key} onClick={() => set({ partyType: draft.partyType === p.key ? null : p.key })}>{p.label}</Chip>
                  ))}
                </div>
              </div>
            </Section>

            <Section title="Budget" hint={draft.days > 1 ? "For the whole trip — it's split evenly across the days." : "For the whole party, excluding travel."}>
              <div className="flex flex-wrap items-center gap-2">
                {BUDGETS.map((b) => (
                  <Chip key={b} className="h-9" selected={draft.budget === b} onClick={() => set({ budget: draft.budget === b ? null : b })}>{rupees(b)}</Chip>
                ))}
                <label htmlFor="budget" className="sr-only">Budget in rupees</label>
                <Input id="budget" inputMode="numeric" placeholder="Custom ₹" className="h-10 w-32"
                  value={draft.budget ?? ""} onChange={(e) => set({ budget: e.target.value ? Number(e.target.value.replace(/\D/g, "").slice(0, 6)) : null })} />
                {draft.budget === null && <span className="text-sm text-muted-foreground">No limit</span>}
              </div>
            </Section>

            <Section title="Pace and extras">
              <Segmented label="Pace" value={draft.pace} onChange={(v) => set({ pace: v })}
                options={[{ value: "quick" as const, label: "Quick" }, { value: "balanced" as const, label: "Balanced" }, { value: "relaxed" as const, label: "Relaxed" }]} />
              <p className="mb-2 mt-4 text-sm font-semibold">Meals to include</p>
              <div className="flex flex-wrap gap-2">
                {MEALS.map((m) => (
                  <Chip key={m.key} className="h-9" selected={draft.meals.includes(m.key)} onClick={() => set({ meals: toggle(draft.meals, m.key) })}>{m.label}</Chip>
                ))}
              </div>
              <div className="mt-4">
                <Field id="area" label="Around an area (optional)" hint="Only areas NavigIQ can place exactly are used.">
                  <Input id="area" value={draft.area} placeholder="Indiranagar, Malleshwaram…" onChange={(e) => set({ area: e.target.value })} />
                </Field>
              </div>
              {includePoi.data && (
                <div className="mt-4">
                  <p className="mb-2 text-sm font-semibold">Must include</p>
                  <Badge tone="primary" className="gap-2 py-1.5 pl-3 pr-1.5">
                    <MapPin aria-hidden="true" /> {(includePoi.data as PoiDetail).name}
                    <button type="button" onClick={() => set({ mustInclude: [] })} aria-label="Remove required place" className="grid size-5 place-items-center rounded-full hover:bg-primary/15">
                      <X className="size-3" aria-hidden="true" />
                    </button>
                  </Badge>
                </div>
              )}
            </Section>
          </div>

          <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
            <div className="rounded-3xl bg-card p-5 ring-1 ring-border/60">
              <h2 className="font-display text-lg font-semibold">Ready when you are</h2>
              <ul className="mt-3 space-y-1.5 text-sm text-muted-foreground">
                <li className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-success" aria-hidden="true" />{dateLabel(draft.date, true)}{draft.days > 1 ? ` + ${draft.days - 1} more day${draft.days > 2 ? "s" : ""}` : ""}, {draft.start}–{draft.end}</li>
                <li className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-success" aria-hidden="true" />{plural(draft.partySize, "person", "people")}{draft.budget ? `, up to ${rupees(draft.budget)}` : ", no budget limit"}</li>
                <li className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-success" aria-hidden="true" />{draft.interests.length + draft.moods.length ? [...draft.interests.map((i) => categoryMeta(i).label), ...draft.moods].join(", ") : "Anything good"}</li>
              </ul>
              <div className="mt-5 space-y-2">
                <Button className="w-full" size="lg" loading={create.isPending} disabled={busy} onClick={() => create.mutate()}>
                  <CalendarPlus aria-hidden="true" /> Build my plan
                </Button>
                <Button variant="secondary" className="w-full" loading={previewRun.isPending} disabled={busy} onClick={() => previewRun.mutate()}>
                  <Eye aria-hidden="true" /> Preview without saving
                </Button>
              </div>
              {busy && <WorkingNote className="mt-3">{elapsed < 3 ? "Choosing places that fit…" : elapsed < 8 ? "Checking opening hours, budget and timings…" : "Still arranging — multi-day trips take longer…"}</WorkingNote>}
              {areaNote && <p className="mt-3 rounded-xl bg-warning-soft/70 px-3 py-2 text-xs text-warning">{areaNote}</p>}
            </div>

            {problem && (
              <div role="alert" className="rounded-3xl bg-warning-soft/70 p-5 ring-1 ring-warning/20">
                <p className="flex items-start gap-2 font-semibold text-warning">
                  <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> That doesn't fit yet
                </p>
                <p className="mt-1 text-sm text-foreground/80">{problem.message}</p>
                {problem.relaxations.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {problem.relaxations.map((r) => (
                      <Button key={r.code + r.description} size="sm" variant="secondary" onClick={() => applyRelaxation(r)}>{r.description}</Button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {previewRun.isError && !problem && <ErrorState description="The preview didn't come back." onRetry={() => previewRun.mutate()} />}

            {preview && (
              <div className={cn("animate-rise")}>
                <p className="mb-2 text-sm font-semibold text-muted-foreground">Preview — not saved yet</p>
                <ItineraryPreview it={preview} maxStops={8} />
                <Button className="mt-3 w-full" onClick={() => create.mutate()} loading={create.isPending}>Save this plan</Button>
              </div>
            )}
          </aside>
        </div>
      </main>
      <PageFooter />
    </>
  );
}
