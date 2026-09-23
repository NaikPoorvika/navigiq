import L from "leaflet";
import { MapContainer, Marker, TileLayer } from "react-leaflet";

const pin = L.divIcon({
  className: "",
  html: '<div class="map-pin stop">●</div>',
  iconSize: [32, 32],
  iconAnchor: [16, 16],
});

/** Single-place map. OSM attribution is a licence requirement. */
export default function PlaceMap({ lat, lon }: { lat: number; lon: number }) {
  return (
    <MapContainer center={[lat, lon]} zoom={16} scrollWheelZoom={false} className="map small">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Marker position={[lat, lon]} icon={pin} />
    </MapContainer>
  );
}
