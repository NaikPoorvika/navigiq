/**
 * The plan — NavigIQ's showcase. A validated itinerary (one day or several),
 * changed conversationally or with quick actions. Every change re-plans with
 * the deterministic engine, is re-validated, and becomes a new version; a
 * what-if is shown next to the current plan and changes nothing until applied.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import {
  ArrowLeft, Bookmark, CalendarDays, Check, ChevronRight, CircleAlert, Clock3, Hourglass,
  Info, List, Map as MapIcon, RotateCcw, ShieldCheck, Split, Trash, Users, Wallet, X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { PageFooter } from "@/components/layout/AppShell";
import { LazyMap } from "@/components/map/LazyMap";
import { ChangeSummary } from "@/components/plan/ChangeSummary";
import { ItineraryTimeline, QuickMenu } from "@/components/plan/ItineraryTimeline";
import { WhatIfCompare } from "@/components/plan/WhatIfCompare";
import { Button } from "@/components/ui/button";
import { Dialog, ResponsivePanel } from "@/components/ui/overlay";
import { Badge, ErrorState, Segmented, Skeleton, WorkingNote } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { Comparison, Feasibility, Itinerary, ModifyResponse, Modification, Relaxation } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { clock, costLabel, dateRangeLabel, minutesLabel, plural, rupees } from "@/lib/format";
import { useDocumentTitle } from "@/lib/hooks";
import { CHECKS, PACE_LABEL, daysOf, isTrip } from "@/lib/plan";
import { keptConstraints, quickActions, type QuickAction } from "@/lib/planActions";
import { qk, usePlan, useVersions } from "@/lib/queries";

interface ChangeState {
  summary: string[];
  comparison: Comparison | null;
  previousVersion: number;
}

interface WhatIfState {
  variantId: number;
  variant: Itinerary;
  comparison: Comparison;
  summary: string[];
}

function sentence(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function StatTile({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="rounded-2xl bg-card p-3.5 ring-1 ring-border/60">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground [&_svg]:size-3.5">{icon}{label}</p>
      <p className="mt-1 font-display text-lg font-semibold leading-tight">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function PlanSkeleton() {
  return (
    <main id="main" className="mx-auto max-w-page px-4 py-8 sm:px-6 lg:px-8" aria-busy="true">
      <Skeleton className="h-5 w-24" />
      <Skeleton className="mt-4 h-10 w-2/3" />
      <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20" />)}</div>
      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_24rem]">
        <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-32" />)}</div>
        <Skeleton className="h-96" />
      </div>
    </main>
  );
}

export function PlanPage() {
  const { planId } = useParams({ from: "/plans/$planId" });
  const { version } = useSearch({ from: "/plans/$planId" });
  const id = Number(planId);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const plan = usePlan(id, version);
  const versions = useVersions(id);
  const view = plan.data;
  const it = view?.itinerary;
  const readOnly = Boolean(view && !view.is_current);
  useDocumentTitle(view?.title ?? "Plan");

  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);
  const [mapDay, setMapDay] = useState(1);
  const [openDays, setOpenDays] = useState<number[] | null>(null);
  const [mobileView, setMobileView] = useState<"timeline" | "map">("timeline");
  const [updating, setUpdating] = useState<{ day: number; text: string } | null>(null);
  const [change, setChange] = useState<ChangeState | null>(null);
  const [problem, setProblem] = useState<{ message: string; relaxations: Relaxation[]; day?: number } | null>(null);
  const [whatIfOpen, setWhatIfOpen] = useState(false);
  const [whatIfDay, setWhatIfDay] = useState<number>(0);
  const [whatIf, setWhatIf] = useState<WhatIfState | null>(null);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const days = useMemo(() => (it ? daysOf(it) : []), [it]);
  const trip = isTrip(it);
  useEffect(() => {
    if (it && openDays === null) setOpenDays(days.map((d) => d.day));
  }, [it, days, openDays]);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["plan", id] });
    void qc.invalidateQueries({ queryKey: qk.versions(id) });
    void qc.invalidateQueries({ queryKey: qk.plans });
  };

  const handleError = (err: unknown, day?: number) => {
    if (err instanceof ApiError) {
      if (err.code === "INFEASIBLE") {
        const feas = (err.details?.feasibility ?? {}) as Feasibility;
        setProblem({ message: feas.message ?? err.message, relaxations: feas.suggested_relaxations ?? [], day: feas.day ?? day });
        return;
      }
      if (err.code === "CONFLICT") {
        toast("This plan changed in another tab", { description: "Showing the latest version." });
        refresh();
        return;
      }
      toast.error(sentence(err.message));
      return;
    }
    toast.error("That change didn't go through. Try again.");
  };

  const modify = useMutation({
    mutationFn: ({ ops }: { ops: Modification[]; day: number; text: string }) =>
      endpoints.modify(id, ops, view?.version_no),
    onMutate: ({ day, text }) => {
      setProblem(null);
      setChange(null);
      setUpdating({ day, text });
    },
    onSuccess: (res: ModifyResponse) => {
      setChange({ summary: res.summary, comparison: res.comparison, previousVersion: view!.version_no });
      refresh();
    },
    onError: (err, { day }) => handleError(err, day),
    onSettled: () => setUpdating(null),
  });

  const whatIfRun = useMutation({
    mutationFn: (ops: Modification[]) => endpoints.whatIf(id, ops),
    onSuccess: (res) => {
      if (res.itinerary && res.variant_id && res.comparison) {
        setWhatIf({ variantId: res.variant_id, variant: res.itinerary, comparison: res.comparison, summary: res.summary });
      }
      void qc.invalidateQueries({ queryKey: qk.versions(id) });
    },
    onError: (err) => {
      setWhatIfOpen(false);
      handleError(err);
    },
  });

  const [variantBusy, setVariantBusy] = useState<"keep" | "apply" | null>(null);
  const resolveVariant = async (apply: boolean) => {
    if (!whatIf || !view) return;
    setVariantBusy(apply ? "apply" : "keep");
    try {
      if (apply) {
        await endpoints.applyVariant(id, whatIf.variantId);
        setChange({ summary: whatIf.summary, comparison: whatIf.comparison, previousVersion: view.version_no });
        toast.success("What-if applied as a new version");
      } else {
        await endpoints.rejectVariant(id, whatIf.variantId);
        toast("Kept your current plan");
      }
      setWhatIf(null);
      setWhatIfOpen(false);
      refresh();
    } catch (err) {
      handleError(err);
    } finally {
      setVariantBusy(null);
    }
  };

  const restore = useMutation({
    mutationFn: (v: number) => endpoints.restore(id, v),
    onSuccess: (res) => {
      toast.success(`Restored — now version ${res.version_no}`);
      setChange(null);
      setVersionsOpen(false);
      void navigate({ to: "/plans/$planId", params: { planId }, search: {} });
      refresh();
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === "VALIDATION_FAILED") {
        toast.error("That version no longer passes today's checks (hours or places changed), so it can't be restored.");
      } else handleError(err);
    },
  });

  const save = useMutation({
    mutationFn: () => endpoints.savePlan(id),
    onSuccess: () => { toast.success("Plan saved"); refresh(); },
    onError: (e) => handleError(e),
  });

  const remove = useMutation({
    mutationFn: () => endpoints.deletePlan(id),
    onSuccess: () => {
      toast("Plan deleted");
      void qc.invalidateQueries({ queryKey: qk.plans });
      void navigate({ to: "/plans" });
    },
    onError: (e) => handleError(e),
  });

  if (plan.isPending) return <PlanSkeleton />;
  if (plan.isError || !view || !it) {
    const notFound = plan.error instanceof ApiError && plan.error.status === 404;
    return (
      <main id="main" className="mx-auto max-w-2xl px-4 py-16">
        <ErrorState
          title={notFound ? "We couldn't find that plan" : "The plan didn't load"}
          description={notFound ? "It may have been deleted, or it belongs to another account or browser." : "Check your connection and try again."}
          onRetry={notFound ? undefined : () => void plan.refetch()}
        />
        <Button asChild variant="ghost" className="mt-4"><Link to="/plans"><ArrowLeft aria-hidden="true" /> All plans</Link></Button>
      </main>
    );
  }

  const spec = view.trip_spec;
  const s = it.summary;
  const busy = modify.isPending || restore.isPending;
  const run = (a: QuickAction, day?: number) => {
    const constraints = keptConstraints(it, spec, day);
    modify.mutate({
      ops: a.ops, day: day ?? 0,
      text: `${a.doing}… keeping ${constraints.join(", ") || "your other choices"}.`,
    });
  };
  const removeStop = (day: number, seq: number, name: string) =>
    modify.mutate({
      ops: [{ op: "remove_stop", target_seq: seq, ...(trip ? { day } : {}) }], day: trip ? day : 0,
      text: `Removing ${name} and re-checking ${trip ? `day ${day}` : "the plan"}…`,
    });
  const replaceStop = (day: number, seq: number, name: string, category?: string) =>
    modify.mutate({
      ops: [{ op: "replace_stop", target_seq: seq, ...(category ? { category } : {}), ...(trip ? { day } : {}) }], day: trip ? day : 0,
      text: `Finding a replacement for ${name}${trip ? ` on day ${day}` : ""}…`,
    });
  const applyRelaxation = (r: Relaxation) => {
    const op = { ...r.operation } as Modification;
    if (trip && problem?.day && !op.day && op.op !== "set_budget") op.day = problem.day;
    modify.mutate({ ops: [op], day: op.day ?? 0, text: `${r.description}…` });
  };

  const mapDays = trip ? days.filter((d) => d.day === mapDay) : days;
  const pins = mapDays.flatMap((d) => d.stops.map((st) => ({
    id: st.seq, lat: st.poi.lat, lon: st.poi.lon, title: st.poi.name, label: st.day_seq ?? st.seq,
  })));
  const selectStop = (seq: number) => {
    setSelectedSeq(seq);
    const st = it.stops.find((x) => x.seq === seq);
    if (st?.day && st.day !== mapDay) setMapDay(st.day);
  };
  const pickPin = (pid: number | string) => {
    const seq = Number(pid);
    setSelectedSeq(seq);
    document.getElementById(`stop-${seq}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const withinBudget = s.budget === null ? null : s.within_budget;
  const currentVersions = (versions.data?.versions ?? []).filter((v) => v.kind === "version");

  const mapCard = (
    <div className="overflow-hidden rounded-3xl bg-card ring-1 ring-border/60">
      {trip && (
        <div className="scrollbar-none flex gap-1.5 overflow-x-auto border-b border-border/60 p-2" role="tablist" aria-label="Day shown on the map">
          {days.map((d) => (
            <button
              key={d.day}
              type="button"
              role="tab"
              aria-selected={mapDay === d.day}
              onClick={() => setMapDay(d.day)}
              className={cn("h-8 shrink-0 rounded-full px-3 text-xs font-semibold", mapDay === d.day ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-surface")}
            >
              Day {d.day}
            </button>
          ))}
        </div>
      )}
      <LazyMap
        label={trip ? `Map of day ${mapDay}` : "Map of the plan"}
        className="h-80 lg:h-[26rem]"
        pins={pins}
        selectedId={selectedSeq}
        onSelect={pickPin}
      />
      <p className="flex items-start gap-2 px-4 py-3 text-xs text-muted-foreground">
        <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
        Pins are numbered in visiting order. No route is drawn: travel between stops isn't calculated yet.
      </p>
    </div>
  );

  return (
    <>
      <main id="main" className="mx-auto max-w-page px-4 pb-8 pt-6 sm:px-6 lg:px-8">
        <nav aria-label="Breadcrumb" className="text-sm">
          <Link to="/plans" className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-4" aria-hidden="true" /> Plans
          </Link>
        </nav>

        {readOnly && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-info-soft px-4 py-3 text-sm text-info">
            <p>You're looking at version {view.version_no}{view.label ? ` (${view.label})` : ""}. The current plan is unchanged.</p>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => void navigate({ to: "/plans/$planId", params: { planId }, search: {} })}>Back to current</Button>
              <Button size="sm" onClick={() => restore.mutate(view.version_no)} loading={restore.isPending}><RotateCcw aria-hidden="true" /> Restore this version</Button>
            </div>
          </div>
        )}

        <header className="mt-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="success" title="Every stop passed NavigIQ's independent checks"><ShieldCheck aria-hidden="true" /> Checked</Badge>
            {trip && <Badge tone="info">{plural(days.length, "day")}</Badge>}
            <Badge>{PACE_LABEL[s.pace] ?? s.pace} pace</Badge>
            {view.status === "saved" && <Badge tone="primary"><Bookmark aria-hidden="true" /> Saved</Badge>}
            <span className="text-xs text-muted-foreground">Version {view.version_no}</span>
          </div>
          <h1 className="mt-3 font-display text-3xl font-semibold tracking-tight sm:text-headline">{it.title}</h1>
          <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><CalendarDays className="size-4" aria-hidden="true" />{dateRangeLabel(it.date, it.end_date)}</span>
            {!trip && <span className="inline-flex items-center gap-1.5"><Clock3 className="size-4" aria-hidden="true" />{clock(it.start_time)} – {clock(it.end_time)}</span>}
            <span className="inline-flex items-center gap-1.5"><Users className="size-4" aria-hidden="true" />{plural(s.party_size, "person", "people")}</span>
          </p>
        </header>

        <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile icon={<Wallet aria-hidden="true" />} label="Estimated cost" value={costLabel(s.estimated_cost)} hint={`for ${plural(s.party_size, "person", "people")} · excludes transport`} />
          <StatTile
            icon={<Check aria-hidden="true" />}
            label="Budget"
            value={s.budget === null ? "No limit set" : withinBudget ? "Within budget" : "Over budget"}
            hint={s.budget !== null ? `${rupees(s.budget)} total${s.max_may_exceed_budget ? " · the top of the range may exceed it" : ""}` : "Add one with Change"}
          />
          <StatTile icon={<List aria-hidden="true" />} label="Stops" value={s.stop_count} hint={trip ? `across ${plural(days.length, "day")}` : `${minutesLabel(s.total_visit_minutes)} of visits`} />
          <StatTile icon={<Hourglass aria-hidden="true" />} label="Between stops" value={`${it.transition_buffer_minutes} min`} hint="buffer — travel not calculated" />
        </div>

        {!readOnly && (
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <QuickMenu actions={quickActions(it, spec)} onRun={(a) => run(a)} disabled={busy} label={trip ? "Change the whole trip" : "Change the plan"} />
            <Button variant="outline" size="sm" onClick={() => { setWhatIf(null); setWhatIfDay(0); setWhatIfOpen(true); }} disabled={busy}>
              <Split aria-hidden="true" /> Try a what-if
            </Button>
            <Button variant="outline" size="sm" onClick={() => setVersionsOpen(true)}>
              Versions{currentVersions.length > 1 ? ` (${currentVersions.length})` : ""}
            </Button>
            {view.status !== "saved" && (
              <Button variant="soft" size="sm" onClick={() => save.mutate()} loading={save.isPending}><Bookmark aria-hidden="true" /> Save plan</Button>
            )}
            <Button variant="ghost" size="sm" className="ml-auto text-danger hover:bg-danger-soft" onClick={() => setConfirmDelete(true)}>
              <Trash aria-hidden="true" /> Delete
            </Button>
          </div>
        )}

        {change && (
          <div className="mt-5 animate-rise" role="status">
            <div className="relative">
              <ChangeSummary comparison={change.comparison} summary={change.summary} title="Plan updated" className="bg-success-soft/40 ring-success/20" />
              <div className="absolute right-3 top-3 flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => restore.mutate(change.previousVersion)} loading={restore.isPending}>
                  <RotateCcw aria-hidden="true" /> Undo
                </Button>
                <Button size="icon-sm" variant="ghost" onClick={() => setChange(null)} aria-label="Dismiss"><X aria-hidden="true" /></Button>
              </div>
            </div>
          </div>
        )}

        {problem && (
          <div role="alert" className="mt-5 rounded-2xl bg-warning-soft/70 p-4 ring-1 ring-warning/20">
            <p className="flex items-start gap-2 font-semibold text-warning">
              <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> That change doesn't fit — your plan is unchanged.
            </p>
            <p className="mt-1 text-sm text-foreground/80">{sentence(problem.message)}</p>
            {problem.relaxations.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {problem.relaxations.map((r) => (
                  <Button key={r.code + r.description} size="sm" variant="secondary" onClick={() => applyRelaxation(r)} disabled={busy}>
                    {r.description}
                  </Button>
                ))}
              </div>
            )}
            <Button size="sm" variant="ghost" className="mt-2" onClick={() => setProblem(null)}>Dismiss</Button>
          </div>
        )}

        <div className="mt-6 md:hidden">
          <Segmented
            label="View"
            value={mobileView}
            onChange={setMobileView}
            options={[{ value: "timeline", label: "Timeline" }, { value: "map", label: "Map" }]}
          />
        </div>

        <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_24rem]">
          <div className={cn(mobileView === "map" && "hidden md:block")}>
            <p className="mb-5 flex items-start gap-2 rounded-2xl bg-surface/80 px-4 py-3 text-sm text-muted-foreground">
              <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              {it.transition_note}
            </p>
            <ItineraryTimeline
              it={it}
              spec={spec}
              selectedSeq={selectedSeq}
              onSelectStop={selectStop}
              onRun={run}
              onRemove={removeStop}
              onReplace={replaceStop}
              updatingDay={updating ? updating.day : null}
              updatingText={updating?.text}
              readOnly={readOnly}
              openDays={openDays ?? days.map((d) => d.day)}
              onToggleDay={(d, o) => setOpenDays((cur) => {
                const base = cur ?? days.map((x) => x.day);
                return o ? [...new Set([...base, d])] : base.filter((x) => x !== d);
              })}
            />
          </div>

          <aside className={cn("space-y-4 lg:sticky lg:top-20 lg:self-start", mobileView === "timeline" && "hidden md:block")} aria-label="Plan details">
            {mapCard}
            <section className="rounded-3xl bg-card p-4 ring-1 ring-border/60">
              <h2 className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck className="size-4 text-success" aria-hidden="true" /> Checked before you saw it</h2>
              <ul className="mt-2 space-y-1.5 text-sm text-muted-foreground">
                {CHECKS.map((c) => <li key={c} className="flex items-start gap-2"><Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden="true" />{c}</li>)}
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">Hours marked unverified are typical hours for that kind of place.</p>
            </section>
            {it.assumptions.length > 0 && (
              <section className="rounded-3xl bg-card p-4 ring-1 ring-border/60">
                <h2 className="text-sm font-semibold">Assumptions</h2>
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {it.assumptions.map((a) => <li key={a}><Badge>{a}</Badge></li>)}
                </ul>
                {!readOnly && <p className="mt-2 text-xs text-muted-foreground">Change any of these with “Change” above.</p>}
              </section>
            )}
            {it.notes.length > 0 && (
              <section className="rounded-3xl bg-card p-4 ring-1 ring-border/60">
                <h2 className="text-sm font-semibold">Notes</h2>
                <ul className="mt-2 space-y-1 text-sm text-muted-foreground">{it.notes.map((n) => <li key={n}>{n}</li>)}</ul>
              </section>
            )}
          </aside>
        </div>
      </main>
      <PageFooter />

      <ResponsivePanel
        open={whatIfOpen}
        onOpenChange={(o) => {
          if (!o && whatIf && !variantBusy) void resolveVariant(false);
          if (!o) { setWhatIfOpen(false); setWhatIf(null); }
        }}
        title={whatIf ? "Compare with your current plan" : "Try a what-if"}
        description={whatIf ? "Nothing changes until you apply it." : "See a variation side by side. Your plan stays as it is."}
        wide={Boolean(whatIf)}
      >
        {whatIf ? (
          <WhatIfCompare current={it} variant={whatIf.variant} comparison={whatIf.comparison} summary={whatIf.summary}
            onKeep={() => void resolveVariant(false)} onApply={() => void resolveVariant(true)} busy={variantBusy} />
        ) : whatIfRun.isPending ? (
          <WorkingNote className="py-8">Planning the variation and running the same checks…</WorkingNote>
        ) : (
          <div className="space-y-4">
            {trip && (
              <div>
                <p className="mb-2 text-sm font-semibold">Apply it to</p>
                <div className="flex flex-wrap gap-2">
                  {[0, ...days.map((d) => d.day)].map((d) => (
                    <button key={d} type="button" aria-pressed={whatIfDay === d} onClick={() => setWhatIfDay(d)}
                      className={cn("h-9 rounded-full border px-3.5 text-sm font-medium", whatIfDay === d ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-surface")}>
                      {d === 0 ? "Whole trip" : `Day ${d}`}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <ul className="grid gap-2 sm:grid-cols-2">
              {quickActions(it, spec, whatIfDay || undefined).map((a) => (
                <li key={a.id}>
                  <button
                    type="button"
                    disabled={Boolean(a.disabled)}
                    onClick={() => whatIfRun.mutate(a.ops)}
                    className="flex w-full items-center justify-between rounded-2xl bg-sand-50 px-4 py-3 text-left text-sm font-medium ring-1 ring-border/70 transition-colors hover:bg-surface disabled:opacity-45"
                  >
                    <span>What if it was {a.label.replace(/^Make it /, "").toLowerCase()}?</span>
                    {a.disabled ? <span className="text-xs text-muted-foreground">{a.disabled}</span> : <ChevronRight className="size-4 text-muted-foreground" aria-hidden="true" />}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </ResponsivePanel>

      <ResponsivePanel open={versionsOpen} onOpenChange={setVersionsOpen} title="Versions" description="Every change is kept. Restoring makes a new version; nothing is overwritten.">
        {versions.isPending ? <WorkingNote>Loading versions…</WorkingNote> : (
          <ol className="space-y-2">
            {[...currentVersions].reverse().map((v) => (
              <li key={v.version_no} className="flex items-center justify-between gap-3 rounded-2xl bg-sand-50 px-4 py-3 ring-1 ring-border/60">
                <div className="min-w-0">
                  <p className="text-sm font-semibold">
                    Version {v.version_no}
                    {v.is_current && <Badge tone="primary" className="ml-2">Current</Badge>}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">{v.label ?? v.reason} · {plural(v.stop_count, "stop")} · {rupees(v.estimated_cost_typical)} est.</p>
                </div>
                {!v.is_current && v.version_no && (
                  <div className="flex shrink-0 gap-1.5">
                    <Button size="sm" variant="ghost" onClick={() => { setVersionsOpen(false); void navigate({ to: "/plans/$planId", params: { planId }, search: { version: v.version_no! } }); }}>
                      <MapIcon aria-hidden="true" /> View
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => restore.mutate(v.version_no!)} loading={restore.isPending && restore.variables === v.version_no}>
                      Restore
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
      </ResponsivePanel>

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete} title="Delete this plan?"
        description="This removes the plan and all its versions. It can't be undone."
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            <Button variant="danger" onClick={() => remove.mutate()} loading={remove.isPending}>Delete plan</Button>
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">“{it.title}” — {plural(s.stop_count, "stop")}.</p>
      </Dialog>
    </>
  );
}

