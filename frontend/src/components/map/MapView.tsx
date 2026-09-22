/**
 * Map of places. Pins only — deliberately NO lines between stops: NavigIQ
 * does not calculate routes or travel times yet, and a drawn line would
 * suggest it does. Numbered pins follow the itinerary order.
 */
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useMemo } from "react";
import { MapContainer, Marker, TileLayer, Tooltip, useMap } from "react-leaflet";

export interface MapPin {
  id: number | string;
  lat: number;
  lon: number;
  title: string;
  /** Shown inside the pin (itinerary order); omitted for plain places. */
  label?: string | number;
  tone?: "primary" | "accent" | "muted";
}

interface Props {
  pins: MapPin[];
  selectedId?: number | string | null;
  onSelect?: (id: number | string) => void;
  className?: string;
  /** Accessible name for the map region. */
  label: string;
  interactive?: boolean;
}

const CENTER: [number, number] = [12.9716, 77.5946];

function pinIcon(pin: MapPin, selected: boolean): L.DivIcon {
  const bg = pin.tone === "accent" ? "#a6532d" : pin.tone === "muted" ? "#7c8663" : "#39412f";
  const size = selected ? 38 : 32;
  const text = pin.label !== undefined ? String(pin.label) : "";
  const html = `
    <div style="position:relative;width:${size}px;height:${size + 8}px;transform:translate(-50%,-100%);">
      <svg width="${size}" height="${size + 8}" viewBox="0 0 32 40" style="filter:drop-shadow(0 3px 6px rgb(0 0 0 / .28))">
        <path d="M16 1C7.7 1 1 7.5 1 15.6 1 26.5 16 39 16 39s15-12.5 15-23.4C31 7.5 24.3 1 16 1Z" fill="${bg}" stroke="#fbf8f2" stroke-width="${selected ? 3 : 2}"/>
      </svg>
      <span style="position:absolute;top:${selected ? 8 : 6}px;left:0;width:100%;text-align:center;color:#fbf8f2;font:600 ${selected ? 14 : 12}px 'DM Sans',sans-serif;">${text || "•"}</span>
    </div>`;
  return L.divIcon({ html, className: "navigiq-pin", iconSize: [0, 0] });
}

function FitBounds({ pins }: { pins: MapPin[] }) {
  const map = useMap();
  const key = pins.map((p) => `${p.id}:${p.lat.toFixed(4)},${p.lon.toFixed(4)}`).join("|");
  useEffect(() => {
    if (!pins.length) return;
    if (pins.length === 1) {
      map.setView([pins[0]!.lat, pins[0]!.lon], 14, { animate: false });
      return;
    }
    const bounds = L.latLngBounds(pins.map((p) => [p.lat, p.lon] as [number, number]));
    map.fitBounds(bounds, { padding: [48, 48], maxZoom: 15, animate: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map]);
  return null;
}

function FlyToSelected({ pins, selectedId }: { pins: MapPin[]; selectedId?: number | string | null }) {
  const map = useMap();
  useEffect(() => {
    if (selectedId === undefined || selectedId === null) return;
    const p = pins.find((x) => x.id === selectedId);
    if (p && !map.getBounds().pad(-0.15).contains([p.lat, p.lon])) {
      map.panTo([p.lat, p.lon], { animate: !window.matchMedia("(prefers-reduced-motion: reduce)").matches });
    }
  }, [selectedId, pins, map]);
  return null;
}

export default function MapView({ pins, selectedId, onSelect, className, label, interactive = true }: Props) {
  const icons = useMemo(
    () => new Map(pins.map((p) => [p.id, pinIcon(p, p.id === selectedId)])),
    [pins, selectedId],
  );
  return (
    <div role="region" aria-label={label} className={className}>
      <MapContainer
        center={CENTER}
        zoom={11}
        scrollWheelZoom={false}
        dragging={interactive}
        zoomControl={interactive}
        className="size-full rounded-[inherit]"
        attributionControl
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          maxZoom={19}
        />
        <FitBounds pins={pins} />
        <FlyToSelected pins={pins} selectedId={selectedId} />
        {pins.map((p) => (
          <Marker
            key={p.id}
            position={[p.lat, p.lon]}
            icon={icons.get(p.id)}
            title={p.title}
            alt={p.label !== undefined ? `${p.label}. ${p.title}` : p.title}
            keyboard
            zIndexOffset={p.id === selectedId ? 1000 : 0}
            eventHandlers={{ click: () => onSelect?.(p.id) }}
          >
            <Tooltip direction="top" offset={[0, -34]}>{p.label !== undefined ? `${p.label}. ` : ""}{p.title}</Tooltip>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
