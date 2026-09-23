import { categoryIcon } from "../lib/categories";
import { tileXY } from "../lib/tiles";

const ZOOM = 16;
const TILE = 256;

/**
 * A small map of the place's ACTUAL location, used when no real photo exists.
 * Real and specific to this place - unlike a stock photo. Four OSM tiles,
 * positioned so the place sits in the centre; attribution is required.
 */
export default function MapSnippet({ lat, lon, category }: { lat: number; lon: number; category: string }) {
  const { x, y } = tileXY(lat, lon, ZOOM);
  const x0 = Math.floor(x - 0.5);
  const y0 = Math.floor(y - 0.5);
  const px = (x - x0) * TILE;
  const py = (y - y0) * TILE;
  const Icon = categoryIcon(category);

  return (
    <div className="map-snippet">
      <div className="snippet-tiles" style={{ transform: `scale(1.25) translate(${-px}px, ${-py}px)` }}>
        {[[0, 0], [1, 0], [0, 1], [1, 1]].map(([dx = 0, dy = 0]) => (
          <img
            key={`${dx}-${dy}`}
            src={`https://tile.openstreetmap.org/${ZOOM}/${x0 + dx}/${y0 + dy}.png`}
            alt=""
            loading="lazy"
            style={{ left: dx * TILE, top: dy * TILE }}
          />
        ))}
      </div>
      <span className="snippet-pin"><Icon size={15} aria-hidden="true" /></span>
      <span className="snippet-credit">© OpenStreetMap</span>
    </div>
  );
}
