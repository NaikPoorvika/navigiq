import { useEffect, useState } from "react";
import { categoryIcon } from "../lib/categories";

/**
 * A REAL photo of a real Bengaluru place of this category, from Wikimedia
 * Commons, always captioned with what it actually shows. Written by
 * data/pipelines/category_photos.py; categories without one show their icon.
 */
export interface CategoryPhotoMeta {
  file: string;
  subject: string;
  credit: string;
  license: string;
  source: string;
}

type Manifest = Record<string, CategoryPhotoMeta>;
let cache: Manifest | null = null;
let loading: Promise<Manifest> | null = null;

export function useCategoryPhotos(): Manifest {
  const [manifest, setManifest] = useState<Manifest>(cache ?? {});
  useEffect(() => {
    if (cache) return;
    loading ??= fetch("/images/categories/categories.json")
      .then((r) => (r.ok ? (r.json() as Promise<Manifest>) : {}))
      .catch(() => ({}));
    let alive = true;
    void loading.then((m) => {
      cache = m;
      if (alive) setManifest(m);
    });
    return () => { alive = false; };
  }, []);
  return manifest;
}

interface Props {
  category: string;
  /**
   * Related categories to borrow a real photo from when `category` has none -
   * e.g. a plan idea's other interests. Only for themed cards: a card that
   * LABELS a category (preferences, category tiles) must show its own photo
   * or its icon, never another category's.
   */
  fallbacks?: string[];
  variant?: "tile" | "thumb";
  showCredit?: boolean;
}

export default function CategoryPhoto({ category, fallbacks = [], variant = "tile", showCredit = true }: Props) {
  const manifest = useCategoryPhotos();
  const key = [category, ...fallbacks].find((k) => manifest[k]);
  const meta = key ? manifest[key] : undefined;
  const [failed, setFailed] = useState(false);
  const Icon = categoryIcon(category);

  if (meta && !failed) {
    const caption = `${meta.subject} · Photo: ${meta.credit}, ${meta.license}`;
    return (
      <figure className={`place-image ${variant}`}>
        <img src={`/images/categories/${meta.file}`} alt={meta.subject} title={caption}
             loading="lazy" onError={() => setFailed(true)} />
        {showCredit && (
          <figcaption>
            <a href={meta.source} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
              {caption}
            </a>
          </figcaption>
        )}
      </figure>
    );
  }

  return (
    <div className={`place-image ${variant} icon-tile`} aria-hidden="true">
      <Icon size={variant === "thumb" ? 22 : 38} />
    </div>
  );
}
