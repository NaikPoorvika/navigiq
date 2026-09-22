import { useState } from "react";
import type { PhotoFields } from "../types";
import MapSnippet from "./MapSnippet";

interface Props extends PhotoFields {
  lat: number;
  lon: number;
  category: string;
  alt: string;
  variant?: "card" | "thumb" | "hero";
  showCredit?: boolean;
}

/**
 * The picture for ONE specific place:
 *   1. its real photo from Wikimedia Commons, with the photographer's credit, or
 *   2. a map of its actual location.
 * Never a stock or generated picture - those can't show this place.
 */
export default function PlacePhoto({
  image_url, image_credit, image_license, image_source_url,
  lat, lon, category, alt, variant = "card", showCredit = true,
}: Props) {
  const [failed, setFailed] = useState(false);

  if (image_url && !failed) {
    const credit = `${image_credit ?? "Wikimedia Commons"}${image_license ? ` · ${image_license}` : ""}`;
    return (
      <figure className={`place-image ${variant}`}>
        <img src={image_url} alt={alt} title={`Photo: ${credit}`} loading="lazy" onError={() => setFailed(true)} />
        {showCredit && (
          <figcaption>
            {image_source_url
              ? <a href={image_source_url} target="_blank" rel="noreferrer">Photo: {credit}</a>
              : <>Photo: {credit}</>}
          </figcaption>
        )}
      </figure>
    );
  }

  // The place page already shows a full map further down, so no hero there.
  if (variant === "hero") return null;

  return (
    <div className={`place-image ${variant}`}>
      <MapSnippet lat={lat} lon={lon} category={category} />
    </div>
  );
}
