import { useEffect, useMemo } from "react";
import L from "leaflet";
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import { hhmm, type Itinerary } from "../types";

type LatLng = [number, number];

const LEG_COLOR: Record<string, string> = {
  walking: "#737c5b",
  bike: "#596247",
  auto: "#39412f",
  cab: "#39412f",
  own_car: "#39412f",
};

/** Numbered pin as HTML - avoids Leaflet's default marker image paths, which break under Vite. */
function pin(label: string, variant: "stop" | "origin"): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div class="map-pin ${variant}">${label}</div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
    popupAnchor: [0, -18],
  });
}

function FitBounds({ points }: { points: LatLng[] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length > 0) {
      map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 15 });
    }
  }, [map, points]);
  return null;
}

export default function ItineraryMap({ itinerary }: { itinerary: Itinerary }) {
  const points = useMemo<LatLng[]>(
    () => [
      [itinerary.origin.lat, itinerary.origin.lon],
      ...itinerary.stops.map((s): LatLng => [s.lat, s.lon]),
    ],
    [itinerary],
  );
  const start = points[0] ?? [12.9716, 77.5946];

  return (
    <div className="map-frame">
      <MapContainer center={start} zoom={13} scrollWheelZoom={false} className="map">
        {/* OpenStreetMap attribution is a licence requirement, not optional. */}
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {itinerary.stops.map((s, i) => {
          const from = points[i];
          if (!from) return null;
          const walking = s.mode_from_prev === "walking";
          return (
            <Polyline
              key={`leg-${s.seq}`}
              positions={[from, [s.lat, s.lon]]}
              pathOptions={{
                color: LEG_COLOR[s.mode_from_prev ?? "auto"] ?? "#39412f",
                weight: 4,
                opacity: 0.85,
                dashArray: walking ? "6 8" : "",
              }}
            />
          );
        })}

        <Marker position={start} icon={pin("", "origin")}>
          <Popup>Start — {itinerary.origin.name ?? "your starting point"}</Popup>
        </Marker>

        {itinerary.stops.map((s) => (
          <Marker key={s.seq} position={[s.lat, s.lon]} icon={pin(String(s.seq), "stop")}>
            <Popup>
              <strong>{s.seq}. {s.name}</strong>
              <br />
              {hhmm(s.arrive_min)}–{hhmm(s.depart_min)}
            </Popup>
          </Marker>
        ))}

        <FitBounds points={points} />
      </MapContainer>
      <p className="map-note">
        Lines connect stops in order — they show the sequence, not the exact road route.
      </p>
    </div>
  );
}
