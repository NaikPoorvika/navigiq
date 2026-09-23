import { MapPin } from "lucide-react";
import { categoryIcon, categoryLabel } from "../lib/categories";
import { href } from "../lib/router";
import { distanceLabel, type PoiSummary } from "../types";
import PlacePhoto from "./PlacePhoto";

export default function PoiCard({ poi }: { poi: PoiSummary }) {
  const shown = poi.matched_category || poi.category;
  const Icon = categoryIcon(shown);
  return (
    <a className="poi-card" href={href(`/place/${poi.id}`)}>
      <PlacePhoto
        lat={poi.lat}
        lon={poi.lon}
        image_url={poi.image_url ?? null}
        image_credit={poi.image_credit ?? null}
        image_license={poi.image_license ?? null}
        image_source_url={poi.image_source_url ?? null}
        category={shown}
        alt={poi.name}
        showCredit={false}
      />
      <div className="poi-body">
        <span className="poi-cat"><Icon size={13} aria-hidden="true" /> {categoryLabel(shown)}</span>
        <strong className="poi-name">{poi.name}</strong>
        <span className="poi-meta"><MapPin size={13} aria-hidden="true" /> {distanceLabel(poi.distance_m)} away</span>
      </div>
    </a>
  );
}
