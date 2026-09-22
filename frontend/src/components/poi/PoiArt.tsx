/**
 * The visual for a place. Its own photograph when one exists (Wikimedia
 * Commons, credited), otherwise category artwork: the category's tone, its
 * icon and a contour-map texture that varies per place, so a list of places
 * without photos still reads as a list of distinct places. Never a stock or
 * generated photo that could be mistaken for the place itself.
 */
import { useState } from "react";
import type { PoiCard } from "@/lib/api/types";
import { GROUP_TONE, categoryMeta } from "@/lib/categories";
import { cn } from "@/lib/cn";

interface Props {
  poi: Pick<PoiCard, "id" | "name" | "category" | "image_url" | "image_attribution" | "locality">;
  className?: string;
  /** Show the photo credit over the image (cards) or leave it to the page (detail). */
  credit?: "overlay" | "none";
  iconSize?: "sm" | "md" | "lg";
  eager?: boolean;
}

function hash(seed: string | number): number {
  const s = String(seed);
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

/** Deterministic, subtle variation so two cards never look identical. */
function variant(seed: number) {
  return {
    rotate: (seed % 7) * 3 - 9,
    shiftX: (seed % 5) * 14 - 28,
    shiftY: ((seed >> 3) % 5) * 10 - 20,
    scale: 1 + (((seed >> 5) % 4) * 6) / 100,
    blobX: 12 + ((seed >> 7) % 70),
    blobY: 10 + ((seed >> 9) % 50),
    tint: 88 + ((seed >> 11) % 4) * 4,
    stripe: (seed >> 13) % 3,
  };
}

function Contours({ v }: { v: ReturnType<typeof variant> }) {
  return (
    <svg className="absolute inset-0 -z-10 size-full opacity-[0.28]" viewBox="0 0 200 150" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth="0.9"
        transform={`translate(${v.shiftX} ${v.shiftY}) rotate(${v.rotate} 100 75) scale(${v.scale})`}
      >
        <path d="M-40 126 C 10 100, 55 136, 100 110 S 175 84, 240 104" />
        <path d="M-40 104 C 5 80, 60 114, 108 88 S 170 62, 240 82" />
        <path d="M-40 82 C 12 62, 62 94, 114 68 S 172 44, 240 60" />
        <path d="M-40 60 C 18 42, 74 74, 120 48 S 178 26, 240 40" />
        <path d="M-40 38 C 24 22, 78 52, 126 28 S 182 10, 240 18" />
        <ellipse cx={150 - v.shiftX / 2} cy="120" rx="30" ry="13" />
        <ellipse cx={150 - v.shiftX / 2} cy="120" rx="17" ry="7" />
        {v.stripe === 1 && <path d="M-40 150 L 240 -10" strokeWidth="0.6" />}
        {v.stripe === 2 && <path d="M-40 -10 L 240 150" strokeWidth="0.6" />}
      </g>
    </svg>
  );
}

export function CategoryArt({ category, seed = 0, className, iconSize = "md" }: {
  category: string; seed?: number | string; className?: string; iconSize?: "sm" | "md" | "lg";
}) {
  const meta = categoryMeta(category);
  const tone = GROUP_TONE[meta.group];
  const Icon = meta.icon;
  const v = variant(hash(`${category}:${seed}`));
  const size = iconSize === "lg" ? "size-14 sm:size-16" : iconSize === "sm" ? "size-7" : "size-11";
  return (
    <div
      className={cn("relative isolate grid place-items-center overflow-hidden", tone.bg, tone.ink, className)}
      style={{ filter: `saturate(${v.tint}%)` }}
    >
      <Contours v={v} />
      <div
        className="absolute -z-10 size-32 rounded-full bg-white/35 blur-2xl"
        style={{ left: `${v.blobX}%`, top: `${v.blobY}%` }}
        aria-hidden="true"
      />
      <span
        className="grid place-items-center rounded-full bg-white/35 p-3 shadow-[0_1px_0_rgb(255_255_255/.5)_inset] backdrop-blur-[1px]"
        style={{ transform: `rotate(${v.rotate / 3}deg)` }}
      >
        <Icon className={cn(size, "opacity-85")} strokeWidth={1.3} aria-hidden="true" />
      </span>
    </div>
  );
}

export function PoiArt({ poi, className, credit = "overlay", iconSize = "md", eager }: Props) {
  const [failed, setFailed] = useState(false);
  const photo = poi.image_url && !failed ? poi.image_url : null;
  if (!photo) {
    return <CategoryArt category={poi.category} seed={poi.id ?? poi.name} className={className} iconSize={iconSize} />;
  }
  const a = poi.image_attribution;
  return (
    <div className={cn("relative overflow-hidden bg-surface-strong", className)}>
      <img
        src={photo}
        alt={`Photo of ${poi.name}`}
        loading={eager ? "eager" : "lazy"}
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
        className="size-full object-cover"
      />
      {credit === "overlay" && a?.artist && (
        <span className="absolute bottom-1.5 right-2 max-w-[70%] truncate rounded bg-black/40 px-1.5 py-0.5 text-[10px] text-white/90">
          {a.artist}{a.license ? ` · ${a.license}` : ""}
        </span>
      )}
    </div>
  );
}
