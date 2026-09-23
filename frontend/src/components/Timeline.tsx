import { Fragment } from "react";
import {
  AlertCircle, Bike, Car, CarFront, CarTaxiFront, Clock, ExternalLink, Flag,
  Footprints, MapPin, Repeat, X, type LucideIcon,
} from "lucide-react";
import { categoryIcon, categoryLabel } from "../lib/categories";
import { googleSearchUrl } from "../lib/maps";
import { href } from "../lib/router";
import PlacePhoto from "./PlacePhoto";
import { costLabel, hhmm, type Itinerary } from "../types";

const LEG: Record<string, { icon: LucideIcon; label: string }> = {
  walking: { icon: Footprints, label: "walk" },
  auto: { icon: CarTaxiFront, label: "by auto" },
  cab: { icon: Car, label: "by cab" },
  own_car: { icon: CarFront, label: "drive" },
  bike: { icon: Bike, label: "ride" },
};

interface Props {
  itinerary: Itinerary;
  startTime: string;
  /** Present only where the plan can be changed - not on a saved plan. */
  onSwap?: (poiId: number) => void;
  onRemove?: (poiId: number, category: string) => void;
  canRemove?: boolean;
}

export default function Timeline({ itinerary, startTime, onSwap, onRemove, canRemove = true }: Props) {
  const last = itinerary.stops[itinerary.stops.length - 1];

  return (
    <ol className="timeline">
      <li className="tl-marker">
        <span className="tl-dot"><MapPin size={14} aria-hidden="true" /></span>
        <span><strong>Start</strong> · {itinerary.origin.name ?? "your starting point"}</span>
        <span className="muted">{startTime}</span>
      </li>

      {itinerary.stops.map((s) => {
        const leg = s.mode_from_prev ? LEG[s.mode_from_prev] : undefined;
        const LegIcon = leg?.icon ?? Car;
        const CatIcon = categoryIcon(s.category);
        return (
          <Fragment key={s.seq}>
            {s.mode_from_prev && (
              <li className="tl-leg">
                <LegIcon size={14} aria-hidden="true" />
                {s.travel_minutes_from_prev} min {leg?.label ?? s.mode_from_prev}
              </li>
            )}
            <li className="tl-stop">
              <span className="tl-num">{s.seq}</span>
              <div className="tl-card">
                <PlacePhoto
                  lat={s.lat}
                  lon={s.lon}
                  image_url={s.image_url ?? null}
                  image_credit={s.image_credit ?? null}
                  image_license={s.image_license ?? null}
                  image_source_url={s.image_source_url ?? null}
                  category={s.category}
                  alt={s.name}
                  variant="thumb"
                  showCredit={false}
                />
                <div className="tl-body">
                <div className="tl-top">
                  <span className="tl-cat">
                    <CatIcon size={14} aria-hidden="true" /> {categoryLabel(s.category)}
                  </span>
                  <span className="tl-cost">{costLabel(s)}</span>
                </div>
                <a className="tl-name" href={href(`/place/${s.poi_id}`)}>{s.name}</a>
                <div className="tl-meta">
                  <span><Clock size={13} aria-hidden="true" /> {hhmm(s.arrive_min)}–{hhmm(s.depart_min)}</span>
                  <span>{s.visit_minutes} min here</span>
                  {s.hours_verified === false && (
                    <span className="chip-warn" title="Opening hours for this place aren't in our data — check before you go">
                      <AlertCircle size={12} aria-hidden="true" /> Hours unverified
                    </span>
                  )}
                {(onSwap || onRemove) && (
                  <div className="tl-actions">
                    {onSwap && (
                      <button type="button" onClick={() => onSwap(s.poi_id)}
                              title={`Find a different ${categoryLabel(s.category).toLowerCase()}`}>
                        <Repeat size={13} aria-hidden="true" /> Swap
                      </button>
                    )}
                    {onRemove && canRemove && (
                      <button type="button" onClick={() => onRemove(s.poi_id, s.category)}
                              title="Drop this stop and replan without it">
                        <X size={13} aria-hidden="true" /> Remove
                      </button>
                    )}
                  </div>
                )}
                </div>
              </div>
            </li>
          </Fragment>
        );
      })}

      {last && (
        <li className="tl-marker">
          <span className="tl-dot"><Flag size={13} aria-hidden="true" /></span>
          <span><strong>Done</strong></span>
          <span className="muted">{hhmm(last.depart_min)}</span>
        </li>
      )}
    </ol>
  );
}
