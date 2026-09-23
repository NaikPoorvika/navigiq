import { useEffect, useState } from "react";
import {
  AlertCircle, ArrowLeft, CalendarPlus, CheckCircle2, Clock, ExternalLink,
  Navigation, Wallet,
} from "lucide-react";
import { getPoi, PlanError } from "../api/client";
import PlacePhoto from "../components/PlacePhoto";
import PlaceMap from "../components/PlaceMap";
import { categoryIcon, categoryLabel } from "../lib/categories";
import { specFromProfile } from "../lib/defaults";
import { directionsTo, googleSearchUrl } from "../lib/maps";
import { href, navigate } from "../lib/router";
import { DAYS } from "../lib/time";
import { useAccount } from "../store/account";
import { setPendingPlan } from "../store/pending";
import { hhmm, type PoiDetail } from "../types";

function hoursByDay(poi: PoiDetail): string[] {
  return DAYS.map((_, d) => {
    const rows = poi.opening_hours.filter((h) => h.day_of_week === d);
    if (rows.length === 0) return "Closed";
    if (rows.some((h) => h.is_24h)) return "Open 24 hours";
    return rows.map((h) => `${hhmm(h.open_min)}–${hhmm(h.close_min)}`).join(", ");
  });
}

export default function PlacePage({ id }: { id: number }) {
  const { profile } = useAccount();
  const [poi, setPoi] = useState<PoiDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPoi(id)
      .then(setPoi)
      .catch((e) => setError(e instanceof PlanError ? e.message : "Couldn't load this place."));
  }, [id]);

  if (error) {
    return (
      <div className="page-narrow">
        <a className="link" href={href("/")}><ArrowLeft size={15} /> Home</a>
        <div className="error-view"><h3>Place not found</h3><p>{error}</p></div>
      </div>
    );
  }
  if (!poi) return <div className="page-narrow"><div className="poi-hero skeleton" /></div>;

  const Icon = categoryIcon(poi.category);
  const verified = poi.opening_hours.some((h) => h.verified);
  const osmUrl = `https://www.openstreetmap.org/${poi.source_ref}`;
  const cost = poi.cost_estimate_inr ?? poi.category_typical_inr;
  const today = (new Date().getDay() + 6) % 7; // JS Sunday=0 -> Monday=0

  return (
    <div className="page-narrow place-page step-enter">
      <a className="link" href={href("/")}><ArrowLeft size={15} /> Back</a>

      <PlacePhoto
        lat={poi.lat}
        lon={poi.lon}
        image_url={poi.image_url ?? null}
        image_credit={poi.image_credit ?? null}
        image_license={poi.image_license ?? null}
        image_source_url={poi.image_source_url ?? null}
        category={poi.category}
        alt={poi.name}
        variant="hero"
      />

      <div className="place-head">
        <span className="tl-cat"><Icon size={14} aria-hidden="true" /> {categoryLabel(poi.category)}</span>
        <h1>{poi.name}</h1>
        {poi.description && <p>{poi.description}</p>}
        <div className="stats">
          <span className="stat"><Clock size={14} aria-hidden="true" /> About {poi.visit_minutes} min here</span>
          <span className="stat"><Wallet size={14} aria-hidden="true" />
            {cost === 0 ? "Free" : poi.cost_basis === "poi_specific" ? `₹${cost}` : `≈ ₹${cost} typical`}</span>
          {poi.indoor !== null && <span className="stat">{poi.indoor ? "Indoors" : "Outdoors"}</span>}
        </div>
        <div className="place-actions">
          <button type="button" className="primary inline"
                  onClick={() => { setPendingPlan(specFromProfile(profile, { origin: { name: poi.name, lat: poi.lat, lon: poi.lon } })); navigate("/plan"); }}>
            <CalendarPlus size={17} aria-hidden="true" /> Plan a trip from here
          </button>
          <a className="btn-outline" href={directionsTo(poi.lat, poi.lon)} target="_blank" rel="noreferrer">
            <Navigation size={15} aria-hidden="true" /> Directions
          </a>
          <a className="btn-outline" href={googleSearchUrl(poi.name)} target="_blank" rel="noreferrer">
            Photos & reviews on Google <ExternalLink size={13} aria-hidden="true" />
          </a>
        </div>
      </div>

      <div className="place-grid">
        <section className="card">
          <h2 className="card-title">Opening hours</h2>
          {verified ? (
            <p className="ok-note"><CheckCircle2 size={14} aria-hidden="true" /> From OpenStreetMap</p>
          ) : (
            <p className="chip-warn block"><AlertCircle size={14} aria-hidden="true" /> Typical hours for this kind of place — not confirmed. Check before you go.</p>
          )}
          <table className="hours">
            <tbody>
              {hoursByDay(poi).map((h, d) => (
                <tr key={DAYS[d]} className={d === today ? "today" : ""}>
                  <th>{DAYS[d]}</th><td>{h}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="card">
          <h2 className="card-title">Location</h2>
          <PlaceMap lat={poi.lat} lon={poi.lon} />
          <div className="map-links">
            <a className="link" href={googleSearchUrl(poi.name)} target="_blank" rel="noreferrer">
              Open in Google Maps <ExternalLink size={13} aria-hidden="true" />
            </a>
            <a className="link" href={osmUrl} target="_blank" rel="noreferrer">
              View on OpenStreetMap <ExternalLink size={13} aria-hidden="true" />
            </a>
          </div>
        </section>
      </div>

      <p className="fine-print">
        Place data © OpenStreetMap contributors. Costs are estimates. NavigIQ doesn't show ratings —
        no reliable free source exists — so use Google for reviews.
      </p>
    </div>
  );
}
