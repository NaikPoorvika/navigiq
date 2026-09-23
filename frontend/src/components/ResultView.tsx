import {
  Cloud, CloudRain, Clock, Footprints, Info, Navigation, RotateCcw, Sun, Wallet,
  type LucideIcon,
} from "lucide-react";
import { categoryLabel } from "../lib/categories";
import { googleMapsUrl } from "../lib/maps";
import { formatDate } from "../lib/time";
import { distanceLabel, durationLabel, hhmm, type PlanResponse, type TripSpec } from "../types";
import ItineraryMap from "./ItineraryMap";
import Timeline from "./Timeline";

function weatherBadge(w: PlanResponse["weather"]): { icon: LucideIcon; text: string } | null {
  if (!w.available) return null;
  const temp = w.mean_temp_c != null ? ` · ${Math.round(w.mean_temp_c)}°C` : "";
  if (w.condition === "heavy_rain") return { icon: CloudRain, text: `Heavy rain likely${temp}` };
  if (w.condition === "light_rain") return { icon: CloudRain, text: `Light rain${temp}` };
  if (w.condition === "clear") return { icon: Sun, text: `Clear${temp}` };
  return { icon: Cloud, text: `${w.condition}${temp}` };
}

interface Props {
  data: PlanResponse;
  spec: TripSpec;
  /**
   * Replan with a changed request. Present on the planner, absent on a saved
   * plan - a stored plan is a record of what happened and isn't edited.
   */
  onChangeSpec?: (spec: TripSpec) => void;
}

export default function ResultView({ data, spec, onChangeSpec }: Props) {

  const it = data.itinerary;
  const first = it.stops[0];
  const last = it.stops[it.stops.length - 1];

  if (!first || !last) {
    return (
      <div className="empty-state">
        <h3>No stops fit this trip</h3>
        <p>Try a longer time window, or mark fewer interests as "Must".</p>
      </div>
    );
  }

  const avoided = spec.constraints.avoid_poi_ids ?? [];

  /** "Not this one": plan the same trip again without that place. */
  function swap(poiId: number) {
    onChangeSpec?.({
      ...spec,
      constraints: { ...spec.constraints, avoid_poi_ids: [...avoided, poiId] },
    });
  }

  /** Drop the stop AND ask for one fewer of its kind, or it comes straight back. */
  function remove(poiId: number, category: string) {
    const interests = spec.interests
      .map((i) => (i.category === category ? { ...i, count: i.count - 1 } : i))
      .filter((i) => i.count > 0);
    onChangeSpec?.({
      ...spec,
      interests: interests.length > 0 ? interests : spec.interests,
      constraints: { ...spec.constraints, avoid_poi_ids: [...avoided, poiId] },
    });
  }

    /** The user picked the replacement: ban the old one, pin the new one. */
  function replaceWith(oldPoiId: number, newPoiId: number) {
    const pinned = (spec.constraints.require_poi_ids ?? []).filter((id) => id !== oldPoiId);
    onChangeSpec?.({
      ...spec,
      constraints: {
        ...spec.constraints,
        avoid_poi_ids: [...avoided, oldPoiId],
        require_poi_ids: [...pinned, newPoiId],
      },
    });
  }

  function showSkippedAgain() {
    onChangeSpec?.({ ...spec, constraints: { ...spec.constraints, avoid_poi_ids: [] } });
  }

  // Removing the last thing asked for would leave nothing to plan.
  const canRemove = spec.interests.reduce((n, i) => n + i.count, 0) > 1;
  const weather = weatherBadge(data.weather);

  // Something asked for that no stop covers. A "must" is reported by the
  // planner; anything softer would otherwise just vanish from the day with
  // no explanation.
  const planned = new Set(it.stops.map((s) => s.category));
  const missing = spec.interests.filter((i) => !planned.has(i.category));

  const notices = [
    ...data.relaxations_applied.map((r) => `Adjusted automatically: ${r}`),
    ...it.unsatisfied_must.map((u) => `Couldn't fully fit a must: ${u.replace(/_/g, " ")}`),
    ...data.semantic_warnings.map((w) => w.message),
  ];

  return (
    <div className="result step-enter">
      <div className="result-head">
        <div>
          <span className="eyebrow">Your plan · {formatDate(spec.date)}</span>
          <h2>{it.stops.length} stops from {it.origin.name ?? "your start"}</h2>
        </div>
        <div className="head-action">
          <a className="btn-outline" href={googleMapsUrl(it)} target="_blank" rel="noreferrer">
            <Navigation size={15} aria-hidden="true" /> Open route in Google Maps
          </a>
          <span className="muted">Google labels stops with its own nearest address — same places.</span>
        </div>
      </div>

      <div className="stats">
        <span className="stat"><Clock size={14} aria-hidden="true" />
          {hhmm(first.arrive_min)}–{hhmm(last.depart_min)} · {durationLabel(it.total_duration_min)}</span>
        <span className="stat"><Wallet size={14} aria-hidden="true" />≈ ₹{it.total_cost_inr} estimated</span>
        <span className="stat"><Footprints size={14} aria-hidden="true" />{distanceLabel(it.total_walk_m)} walking</span>
        {weather && (
          <span className="stat"><weather.icon size={14} aria-hidden="true" />{weather.text}</span>
        )}
      </div>
      {missing.length > 0 && (
        <ul className="notices">
          {missing.map((i) => (
            <li key={i.category}>
              <Info size={14} aria-hidden="true" />
              No {categoryLabel(i.category).toLowerCase()} fitted this trip
              {i.priority === "must" ? " — it was a must, so try a longer window" : ""}
              . There may not be time, or nothing suitable is open nearby.
            </li>
          ))}
        </ul>
      )}
      {notices.length > 0 && (
        <ul className="notices">
          {notices.map((n) => (
            <li key={n}><Info size={14} aria-hidden="true" /> {n}</li>
          ))}
        </ul>
      )}

      {avoided.length > 0 && onChangeSpec && (
        <div className="skipped-note">
          <span>{avoided.length} place{avoided.length > 1 ? "s" : ""} skipped at your request.</span>
          <button type="button" className="link" onClick={showSkippedAgain}>
            <RotateCcw size={14} aria-hidden="true" /> Allow them again
          </button>
        </div>
      )}

      <ItineraryMap itinerary={it} />
      <Timeline
        itinerary={it}
        startTime={spec.start_time_local}
        {...(onChangeSpec
          ? { onSwap: swap, onReplace: replaceWith, onRemove: remove, canRemove }
          : {})}
      />

      <p className="fine-print">
        {it.cost_note ?? "Costs are estimates."} Travel times are estimates from road
        data and time of day, not live traffic. Map data © OpenStreetMap contributors.
      </p>
    </div>
  );
}
