import { Fragment, useEffect, useState } from "react";
import {
  AlertCircle, Bike, Car, CarFront, CarTaxiFront, Clock, ExternalLink, Flag,
  Footprints, MapPin, Repeat, Sparkles, X, type LucideIcon,
} from "lucide-react";
import { searchPois } from "../api/client";
import { categoryIcon, categoryLabel } from "../lib/categories";
import { googleSearchUrl } from "../lib/maps";
import { href } from "../lib/router";
import PlacePhoto from "./PlacePhoto";
import { costLabel, distanceLabel, hhmm, type Itinerary, type PoiSummary, type Stop } from "../types";

const LEG: Record<string, { icon: LucideIcon; label: string }> = {
  walking: { icon: Footprints, label: "walk" },
  auto: { icon: CarTaxiFront, label: "by auto" },
  cab: { icon: Car, label: "by cab" },
  own_car: { icon: CarFront, label: "drive" },
  bike: { icon: Bike, label: "ride" },
};

/** Other places of the same kind, near the one being replaced. */
function SwapPanel({ stop, exclude, onChoose, onAuto, onClose }: {
  stop: Stop;
  exclude: number[];
  onChoose: (poiId: number) => void;
  onAuto: () => void;
  onClose: () => void;
}) {
  const [options, setOptions] = useState<PoiSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    searchPois({ lat: stop.lat, lon: stop.lon, radiusKm: 2,
                 categories: [stop.category], limit: 12 })
      .then((r) => {
        if (alive) setOptions(r.results.filter((p) => !exclude.includes(p.id)).slice(0, 6));
      })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stop.poi_id]);

  return (
    <div className="swap-panel step-enter">
      <div className="swap-head">
        <strong>Replace {stop.name}</strong>
        <button type="button" className="swap-close" onClick={onClose} aria-label="Close">
          <X size={15} />
        </button>
      </div>

      <button type="button" className="swap-option auto" onClick={onAuto}>
        <Sparkles size={15} aria-hidden="true" />
        <span><strong>Let NavigIQ choose</strong>
          <span className="muted">Picks the best fit for your time and route</span></span>
      </button>

      {failed && <p className="field-error">Couldn't load nearby options.</p>}
      {!failed && options === null && <p className="muted">Looking nearby…</p>}
      {options?.length === 0 && (
        <p className="muted">No other {categoryLabel(stop.category).toLowerCase()} within 2 km.</p>
      )}

      {options?.map((p) => (
        <button key={p.id} type="button" className="swap-option" onClick={() => onChoose(p.id)}>
          <MapPin size={15} aria-hidden="true" />
          <span><strong>{p.name}</strong>
            <span className="muted">{distanceLabel(p.distance_m)} from this stop</span></span>
        </button>
      ))}

      <p className="swap-note">
        A replacement is planned into your day — if it can't fit the times, you'll be told.
      </p>
    </div>
  );
}

interface Props {
  itinerary: Itinerary;
  startTime: string;
  /** Present only where the plan can be changed - not on a saved plan. */
  onSwap?: (poiId: number) => void;
  onReplace?: (oldPoiId: number, newPoiId: number) => void;
  onRemove?: (poiId: number, category: string) => void;
  canRemove?: boolean;
}

export default function Timeline({
  itinerary, startTime, onSwap, onReplace, onRemove, canRemove = true,
}: Props) {
  const last = itinerary.stops[itinerary.stops.length - 1];
  const [swapping, setSwapping] = useState<number | null>(null);
  const inPlan = itinerary.stops.map((s) => s.poi_id);

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
                  <a className="tl-ext" href={googleSearchUrl(s.name)} target="_blank" rel="noreferrer">
                    On Google Maps <ExternalLink size={12} aria-hidden="true" />
                  </a>
                </div>
                {(onSwap || onRemove) && (
                  <div className="tl-actions">
                    {onSwap && (
                      <button type="button"
                              onClick={() => setSwapping(swapping === s.poi_id ? null : s.poi_id)}
                              title={`Choose a different ${categoryLabel(s.category).toLowerCase()}`}>
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
                {swapping === s.poi_id && onSwap && (
                  <SwapPanel
                    stop={s}
                    exclude={inPlan}
                    onClose={() => setSwapping(null)}
                    onAuto={() => { setSwapping(null); onSwap(s.poi_id); }}
                    onChoose={(newId) => { setSwapping(null); onReplace?.(s.poi_id, newId); }}
                  />
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