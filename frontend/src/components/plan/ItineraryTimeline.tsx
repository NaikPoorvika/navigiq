/**
 * The itinerary timeline: one section per day (collapsible on trips), each
 * with its own summary, weather, quick changes and the stop timeline.
 */
import * as Collapsible from "@radix-ui/react-collapsible";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { ChevronDown, CloudRain, CloudSun, SlidersHorizontal, Sun } from "lucide-react";
import type { ReactNode } from "react";
import type { Itinerary, TripSpec, WeatherWindow } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { clock, costLabel, dateLabel, minutesLabel, plural } from "@/lib/format";
import { daysOf, isTrip, type DayView } from "@/lib/plan";
import { quickActions, type QuickAction } from "@/lib/planActions";
import { GapRow, StopCard } from "@/components/plan/StopCard";
import { WorkingNote } from "@/components/ui/primitives";

export function WeatherChip({ w }: { w: WeatherWindow | null | undefined }) {
  if (!w) return null;
  if (!w.available) {
    return <span className="inline-flex items-center gap-1 rounded-full bg-surface px-2.5 py-1 text-xs text-muted-foreground">Forecast unavailable</span>;
  }
  const wet = w.rain_likely || w.heavy_rain_expected;
  const Icon = w.heavy_rain_expected || w.rain_likely ? CloudRain : w.condition === "light_rain" ? CloudSun : Sun;
  const text = w.heavy_rain_expected ? "Heavy rain expected" : w.rain_likely ? "Rain likely" : w.condition === "light_rain" ? "Light rain possible" : "Dry";
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium", wet ? "bg-info-soft text-info" : "bg-warning-soft/70 text-warning")}>
      <Icon className="size-3.5" aria-hidden="true" />
      {w.mean_temp_c !== null && `${Math.round(w.mean_temp_c)}°C · `}{text}
    </span>
  );
}

export function QuickMenu({ actions, onRun, disabled, label, children }: {
  actions: QuickAction[]; onRun: (a: QuickAction) => void; disabled?: boolean; label: string; children?: ReactNode;
}) {
  return (
    <Dropdown.Root>
      <Dropdown.Trigger
        disabled={disabled}
        className="inline-flex h-9 items-center gap-1.5 rounded-full border border-border-strong bg-card px-3.5 text-sm font-semibold hover:bg-surface disabled:opacity-50"
        aria-label={label}
      >
        {children ?? <><SlidersHorizontal className="size-4" aria-hidden="true" /> Change</>}
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="end" sideOffset={6} className="z-50 min-w-60 rounded-2xl bg-card p-1.5 shadow-float ring-1 ring-border data-[state=open]:animate-pop">
          <Dropdown.Label className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</Dropdown.Label>
          {actions.map((a) => (
            <Dropdown.Item key={a.id} disabled={Boolean(a.disabled)} onSelect={() => onRun(a)} className="menu-item justify-between">
              <span>{a.label}</span>
              {a.disabled && <span className="text-xs text-muted-foreground">{a.disabled}</span>}
            </Dropdown.Item>
          ))}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

interface TimelineProps {
  it: Itinerary;
  spec: TripSpec;
  selectedSeq: number | null;
  onSelectStop: (seq: number) => void;
  onRun: (action: QuickAction, day?: number) => void;
  onRemove: (day: number, seq: number, name: string) => void;
  onReplace: (day: number, seq: number, name: string, category?: string) => void;
  /** Day currently being re-planned (0 = the whole plan). */
  updatingDay: number | null;
  updatingText?: string;
  readOnly?: boolean;
  openDays: number[];
  onToggleDay: (day: number, open: boolean) => void;
}

function DayHeader({ d, trip, it, spec, onRun, busy, readOnly }: {
  d: DayView; trip: boolean; it: Itinerary; spec: TripSpec; onRun: TimelineProps["onRun"]; busy: boolean; readOnly?: boolean;
}) {
  const summary = d.meta?.summary ?? it.summary;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          {trip ? `Day ${d.day} · ${dateLabel(d.date)}` : dateLabel(d.date, true)}
        </p>
        {trip && <h3 className="mt-0.5 font-display text-xl font-semibold tracking-tight">{d.title}</h3>}
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
          <span>{clock(d.start_time)} – {clock(d.end_time)}</span>
          <span>{plural(d.stops.length, "stop")}</span>
          <span>{costLabel(summary.estimated_cost)} est.</span>
          <WeatherChip w={d.meta?.weather ?? (trip ? null : it.weather)} />
        </p>
      </div>
      {!readOnly && trip && (
        <QuickMenu actions={quickActions(it, spec, d.day)} onRun={(a) => onRun(a, d.day)} disabled={busy} label={`Change day ${d.day}`} />
      )}
    </div>
  );
}

function StopList({ d, props, busy }: { d: DayView; props: TimelineProps; busy: boolean }) {
  const { it, selectedSeq, onSelectStop, onRemove, onReplace, readOnly } = props;
  if (!d.stops.length) {
    return <p className="rounded-2xl bg-surface/70 p-4 text-sm text-muted-foreground">A free day — nothing scheduled.</p>;
  }
  return (
    <ol className="space-y-0" aria-label={isTrip(it) ? `Day ${d.day} stops` : "Stops"}>
      {d.stops.map((s, i) => (
        <StopCard
          key={s.seq}
          stop={s}
          gap={i > 0 ? <GapRow stop={s} bufferNote={i === 1} /> : null}
          selected={selectedSeq === s.seq}
          onSelect={() => onSelectStop(s.seq)}
          onRemove={() => onRemove(d.day, s.day_seq ?? s.seq, s.poi.name)}
          onReplace={(cat) => onReplace(d.day, s.day_seq ?? s.seq, s.poi.name, cat)}
          disabled={busy}
          readOnly={readOnly}
        />
      ))}
    </ol>
  );
}

export function ItineraryTimeline(props: TimelineProps) {
  const { it, spec, updatingDay, updatingText, openDays, onToggleDay, onRun, readOnly } = props;
  const trip = isTrip(it);
  const days = daysOf(it);
  const busy = updatingDay !== null;

  if (!trip) {
    const d = days[0]!;
    return (
      <section aria-label="Timeline" className={cn("relative", busy && "pointer-events-none")} aria-busy={busy}>
        <DayHeader d={d} trip={false} it={it} spec={spec} onRun={onRun} busy={busy} readOnly={readOnly} />
        {busy && <WorkingNote className="mt-4">{updatingText}</WorkingNote>}
        <div className={cn("mt-5 transition-opacity", busy && "opacity-45")}>
          <StopList d={d} props={props} busy={busy} />
        </div>
      </section>
    );
  }

  return (
    <div className="space-y-4">
      {days.map((d) => {
        const open = openDays.includes(d.day);
        const dayBusy = updatingDay === d.day || updatingDay === 0;
        return (
          <Collapsible.Root key={d.day} open={open} onOpenChange={(o) => onToggleDay(d.day, o)} asChild>
            <section
              id={`day-${d.day}`}
              aria-label={`Day ${d.day}`}
              aria-busy={dayBusy}
              className={cn("scroll-mt-24 rounded-[1.75rem] bg-sand-50/80 p-4 ring-1 ring-border/60 sm:p-5", dayBusy && "ring-2 ring-accent/40")}
            >
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <DayHeader d={d} trip it={it} spec={spec} onRun={onRun} busy={busy} readOnly={readOnly} />
                </div>
                <Collapsible.Trigger
                  className="grid size-9 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-surface"
                  aria-label={open ? `Collapse day ${d.day}` : `Expand day ${d.day}`}
                >
                  <ChevronDown className={cn("size-5 transition-transform", open && "rotate-180")} aria-hidden="true" />
                </Collapsible.Trigger>
              </div>
              {dayBusy && <WorkingNote className="mt-4">{updatingText}</WorkingNote>}
              <Collapsible.Content className={cn("mt-5 transition-opacity", dayBusy && "opacity-45")}>
                <StopList d={d} props={props} busy={busy} />
                {d.meta?.notes && d.meta.notes.length > 0 && (
                  <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
                    {d.meta.notes.map((n) => <li key={n}>· {n}</li>)}
                  </ul>
                )}
              </Collapsible.Content>
              {!open && (
                <p className="mt-2 truncate text-sm text-muted-foreground">
                  {d.stops.map((s) => s.poi.name).join(" · ")} · {minutesLabel(d.meta?.summary.total_visit_minutes ?? 0)} of visits
                </p>
              )}
            </section>
          </Collapsible.Root>
        );
      })}
    </div>
  );
}
