import {
  Cloud, CloudRain, Clock, Footprints, Info, Navigation, Sun, Wallet,
  type LucideIcon,
} from "lucide-react";
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
}

export default function ResultView({ data, spec }: Props) {
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

  const weather = weatherBadge(data.weather);
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

      {notices.length > 0 && (
        <ul className="notices">
          {notices.map((n) => (
            <li key={n}><Info size={14} aria-hidden="true" /> {n}</li>
          ))}
        </ul>
      )}

      <ItineraryMap itinerary={it} />
      <Timeline itinerary={it} startTime={spec.start_time_local} />

      <p className="fine-print">
        {it.cost_note ?? "Costs are estimates."} Travel times are estimates from road
        data and time of day, not live traffic. Map data © OpenStreetMap contributors.
      </p>
    </div>
  );
}
