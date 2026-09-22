/**
 * One stop on the timeline, and the gap before it. The gap is a fixed
 * transition buffer (plus any free time) — never a travel time, because
 * NavigIQ doesn't calculate travel yet.
 */
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { Link } from "@tanstack/react-router";
import { Clock3, Ellipsis, ExternalLink, Hourglass, Info, RefreshCw, Sparkles, Trash, Wallet } from "lucide-react";
import type { ReactNode } from "react";
import type { ItineraryStop } from "@/lib/api/types";
import { categoryMeta } from "@/lib/categories";
import { cn } from "@/lib/cn";
import { clock, costLabel, minutesLabel } from "@/lib/format";
import { localSeq } from "@/lib/plan";
import { externalMapUrl } from "@/components/map/LazyMap";
import { CategoryBadge } from "@/components/poi/PoiCard";
import { PoiArt } from "@/components/poi/PoiArt";

export const REPLACE_WITH = ["cafe", "restaurant", "park", "museum", "garden", "lake", "gallery", "temple", "market", "street_food"] as const;

export function GapRow({ stop, bufferNote }: { stop: ItineraryStop; bufferNote: boolean }) {
  const buffer = stop.transition_buffer_before_min;
  const free = stop.free_time_before_min;
  if (!buffer && !free) return null;
  return (
    <div className="relative flex items-center gap-3 py-2 pl-[4.75rem] text-xs text-muted-foreground sm:pl-[5.5rem]">
      <span className="absolute left-[3.05rem] top-0 h-full border-l-2 border-dashed border-border-strong sm:left-[3.8rem]" aria-hidden="true" />
      {buffer > 0 && (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-surface px-2.5 py-1">
          <Hourglass className="size-3" aria-hidden="true" />
          {buffer} min buffer{bufferNote ? " · travel not calculated" : ""}
        </span>
      )}
      {free > 0 && (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-info-soft px-2.5 py-1 text-info">
          <Clock3 className="size-3" aria-hidden="true" />
          {minutesLabel(free)} free
        </span>
      )}
    </div>
  );
}

interface StopProps {
  stop: ItineraryStop;
  selected?: boolean;
  onSelect?: () => void;
  onRemove?: () => void;
  onReplace?: (category?: string) => void;
  disabled?: boolean;
  readOnly?: boolean;
  /** The gap before this stop (buffer / free time), rendered inside the item. */
  gap?: ReactNode;
}

export function StopCard({ stop, selected, onSelect, onRemove, onReplace, disabled, readOnly, gap }: StopProps) {
  const poi = stop.poi;
  const seq = localSeq(stop);
  return (
    <li id={`stop-${stop.seq}`} className="relative" onMouseEnter={onSelect} onFocus={onSelect}>
      {gap}
      <div className="flex gap-3 sm:gap-4">
      <div className="w-[3.25rem] shrink-0 pt-3 text-right sm:w-16">
        <p className="font-display text-sm font-semibold tabular-nums">{clock(stop.arrive)}</p>
        <p className="text-xs tabular-nums text-muted-foreground">{clock(stop.depart)}</p>
      </div>
      <div className="relative flex flex-col items-center">
        <span className={cn(
          "z-10 mt-2.5 grid size-8 place-items-center rounded-full font-display text-sm font-semibold ring-4 ring-background transition-colors",
          selected ? "bg-accent text-accent-foreground" : "bg-primary text-primary-foreground",
        )}>
          {seq}
        </span>
        <span className="absolute top-10 h-[calc(100%-1.5rem)] border-l-2 border-border-strong/70" aria-hidden="true" />
      </div>
      <article
        className={cn(
          "mb-1 flex min-w-0 flex-1 gap-3 rounded-3xl bg-card p-3 shadow-soft ring-1 transition-[box-shadow,ring-color] sm:gap-4",
          selected ? "ring-2 ring-accent/50" : "ring-border/60",
        )}
      >
        <PoiArt poi={poi} className="hidden size-24 shrink-0 rounded-2xl xs:block sm:size-28" iconSize="sm" credit="none" />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <CategoryBadge category={poi.category} className="px-2 py-0.5 text-[11px]" />
              <h4 className="mt-1.5 font-display text-base font-semibold leading-snug">
                <Link to="/places/$placeId" params={{ placeId: String(poi.id) }} className="hover:underline">
                  <span className="sr-only">Stop {seq}: </span>{poi.name}
                </Link>
              </h4>
              {poi.locality && <p className="text-[13px] text-muted-foreground">{poi.locality}</p>}
            </div>
            {!readOnly && (
              <Dropdown.Root>
                <Dropdown.Trigger
                  disabled={disabled}
                  className="grid size-9 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-surface hover:text-foreground disabled:opacity-40"
                  aria-label={`Change stop ${seq}, ${poi.name}`}
                >
                  <Ellipsis className="size-5" aria-hidden="true" />
                </Dropdown.Trigger>
                <Dropdown.Portal>
                  <Dropdown.Content align="end" sideOffset={6} className="z-50 min-w-60 rounded-2xl bg-card p-1.5 shadow-float ring-1 ring-border data-[state=open]:animate-pop">
                    <Dropdown.Item onSelect={() => onReplace?.()} className="menu-item">
                      <RefreshCw aria-hidden="true" /> Replace with something similar
                    </Dropdown.Item>
                    <Dropdown.Sub>
                      <Dropdown.SubTrigger className="menu-item">
                        <Sparkles aria-hidden="true" /> Replace with a…
                      </Dropdown.SubTrigger>
                      <Dropdown.Portal>
                        <Dropdown.SubContent sideOffset={4} className="z-50 max-h-72 min-w-44 overflow-y-auto rounded-2xl bg-card p-1.5 shadow-float ring-1 ring-border">
                          {REPLACE_WITH.filter((c) => c !== poi.category).map((c) => (
                            <Dropdown.Item key={c} onSelect={() => onReplace?.(c)} className="menu-item">
                              {categoryMeta(c).label}
                            </Dropdown.Item>
                          ))}
                        </Dropdown.SubContent>
                      </Dropdown.Portal>
                    </Dropdown.Sub>
                    <Dropdown.Item onSelect={() => onRemove?.()} className="menu-item text-danger [&_svg]:!text-danger">
                      <Trash aria-hidden="true" /> Remove from plan
                    </Dropdown.Item>
                    <Dropdown.Separator className="my-1 h-px bg-border" />
                    <Dropdown.Item asChild className="menu-item">
                      <a href={externalMapUrl(poi.lat, poi.lon)} target="_blank" rel="noopener noreferrer">
                        <ExternalLink aria-hidden="true" /> Open in OpenStreetMap
                        <span className="ml-auto text-[10px] text-muted-foreground">external</span>
                      </a>
                    </Dropdown.Item>
                  </Dropdown.Content>
                </Dropdown.Portal>
              </Dropdown.Root>
            )}
          </div>
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground">
            <span className="inline-flex items-center gap-1"><Clock3 className="size-3.5" aria-hidden="true" />{minutesLabel(stop.visit_minutes)}</span>
            <span className="inline-flex items-center gap-1">
              <Wallet className="size-3.5" aria-hidden="true" />
              <span className="font-medium text-foreground">{costLabel(stop.estimated_cost)}</span>
              {stop.estimated_cost.max > 0 && (stop.estimated_cost.party_size ?? 1) > 1 && <span>for {stop.estimated_cost.party_size}</span>}
            </span>
          </p>
          {stop.why.length > 0 && (
            <p className="mt-1.5 flex items-start gap-1.5 text-[13px] text-primary">
              <Sparkles className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              <span><span className="sr-only">Why: </span>{stop.why.slice(0, 3).join(" · ")}</span>
            </p>
          )}
          {!stop.hours_verified && (
            <p className="mt-1.5 flex items-start gap-1.5 text-xs text-warning">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              Opening hours aren't verified for this place — worth checking before you go.
            </p>
          )}
        </div>
      </article>
      </div>
    </li>
  );
}
