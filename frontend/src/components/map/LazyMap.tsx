/** The map is its own chunk (Leaflet is heavy); it loads only when shown. */
import { lazy, Suspense, type ComponentProps } from "react";
import { cn } from "@/lib/cn";

const MapView = lazy(() => import("@/components/map/MapView"));

export type { MapPin } from "@/components/map/MapView";

export function LazyMap(props: ComponentProps<typeof MapView>) {
  return (
    <Suspense fallback={<div className={cn("skeleton", props.className)} aria-label="Loading map" role="status" />}>
      <MapView {...props} />
    </Suspense>
  );
}

/** Opens the place in an external map app — clearly an external action. */
export function externalMapUrl(lat: number, lon: number): string {
  return `https://www.openstreetmap.org/?mlat=${lat.toFixed(6)}&mlon=${lon.toFixed(6)}#map=17/${lat.toFixed(6)}/${lon.toFixed(6)}`;
}
