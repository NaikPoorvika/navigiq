/**
 * A place. Only fields NavigIQ actually has are shown — no invented ratings,
 * no "popular times", no photos that aren't of this place. Where a fact is
 * uncertain (unverified hours, estimated costs) the page says so.
 */
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import {
  ArrowLeft, CalendarPlus, Check, Clock3, ExternalLink, Info, MapPin, Ruler, Sparkles, Wallet,
} from "lucide-react";
import { PageFooter } from "@/components/layout/AppShell";
import { LazyMap, externalMapUrl } from "@/components/map/LazyMap";
import { CategoryBadge } from "@/components/poi/PoiCard";
import { PoiArt } from "@/components/poi/PoiArt";
import { PoiRail } from "@/components/poi/PoiRail";
import { SaveButton } from "@/components/poi/SaveButton";
import { Button } from "@/components/ui/button";
import { Badge, EmptyState, ErrorState, SectionHeader, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import type { PoiDetail } from "@/lib/api/types";
import { categoryMeta, humanize } from "@/lib/categories";
import { cn } from "@/lib/cn";
import { clock, costLabel, distanceLabel, minutesLabel, parseDate, regionLabel, todayIST } from "@/lib/format";
import { useDocumentTitle } from "@/lib/hooks";
import { usePoi, useSimilar } from "@/lib/queries";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const SUITABILITY: { key: string; label: string }[] = [
  { key: "family_friendly", label: "Families" },
  { key: "kids_friendly", label: "Kids" },
  { key: "senior_friendly", label: "Older visitors" },
  { key: "couple_friendly", label: "Couples" },
  { key: "solo_friendly", label: "Going solo" },
  { key: "group_friendly", label: "Groups" },
];

function Fact({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-2xl bg-card p-4 ring-1 ring-border/60">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground [&_svg]:size-3.5">{icon}{label}</p>
      <p className="mt-1 font-display text-base font-semibold">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Hours({ poi }: { poi: PoiDetail }) {
  if (!poi.opening_hours?.length) return null;
  const todayIdx = parseDate(todayIST()).weekday; // 0 = Sunday
  const todayMon = (todayIdx + 6) % 7;            // backend uses 0 = Monday
  return (
    <section className="rounded-3xl bg-card p-5 ring-1 ring-border/60">
      <h2 className="font-display text-lg font-semibold">Opening hours</h2>
      <table className="mt-3 w-full text-sm">
        <caption className="sr-only">Opening hours by day</caption>
        <tbody>
          {poi.opening_hours.map((h) => (
            <tr key={h.day_of_week} className={cn("border-b border-border/50 last:border-0", h.day_of_week === todayMon && "font-semibold")}>
              <th scope="row" className="py-1.5 text-left font-normal">
                {DAYS[h.day_of_week]}
                {h.day_of_week === todayMon && <span className="ml-2 rounded-full bg-primary-soft px-2 py-0.5 text-[11px] font-semibold text-primary">Today</span>}
              </th>
              <td className="py-1.5 text-right tabular-nums">
                {h.is_24h ? "Open 24 hours" : h.open && h.close ? `${clock(h.open)} – ${clock(h.close)}` : "Closed"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!poi.hours_verified && (
        <p className="mt-3 flex items-start gap-2 rounded-xl bg-warning-soft/70 px-3 py-2 text-xs text-warning">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          These are typical hours for this kind of place, not confirmed for this one. Worth checking before you go.
        </p>
      )}
    </section>
  );
}

export function PlacePage() {
  const { placeId } = useParams({ from: "/places/$placeId" });
  const navigate = useNavigate();
  const id = Number(placeId);
  const q = usePoi(Number.isFinite(id) ? id : placeId);
  const poi = q.data;
  const similar = useSimilar(poi?.id);
  useDocumentTitle(poi?.name);

  if (q.isPending) {
    return (
      <main id="main" className="mx-auto max-w-page px-4 py-6 sm:px-6 lg:px-8" aria-busy="true">
        <Skeleton className="h-64 w-full rounded-3xl sm:h-80" />
        <Skeleton className="mt-6 h-9 w-1/2" />
        <div className="mt-6 grid gap-3 sm:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-24" />)}</div>
      </main>
    );
  }
  if (q.isError || !poi) {
    const notFound = q.error instanceof ApiError && q.error.status === 404;
    return (
      <main id="main" className="mx-auto max-w-2xl px-4 py-16">
        {notFound ? (
          <EmptyState icon={<MapPin aria-hidden="true" />} title="We don't have that place"
            description="It may have been removed from NavigIQ's catalogue."
            action={<Button asChild><Link to="/search">Explore places</Link></Button>} />
        ) : (
          <ErrorState description="This place didn't load." onRetry={() => void q.refetch()} />
        )}
      </main>
    );
  }

  const tags = poi.experience_tags.slice(0, 8);
  const suits = SUITABILITY.filter((s) => poi.suitability?.[s.key] === true);
  const meta = categoryMeta(poi.category);

  return (
    <>
      <main id="main" className="mx-auto max-w-page px-4 pb-10 pt-4 sm:px-6 lg:px-8">
        <nav aria-label="Breadcrumb" className="text-sm">
          <button type="button" onClick={() => history.length > 1 ? history.back() : navigate({ to: "/search" })} className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-4" aria-hidden="true" /> Back
          </button>
        </nav>

        <div className="mt-3 overflow-hidden rounded-[2rem] ring-1 ring-border/60">
          <PoiArt poi={poi} className="h-56 w-full sm:h-80" credit="none" iconSize="lg" eager />
        </div>
        {poi.image_url && poi.image_attribution?.artist && (
          <p className="mt-1.5 text-right text-xs text-muted-foreground">
            Photo: {poi.image_attribution.artist}
            {poi.image_attribution.license ? ` · ${poi.image_attribution.license}` : ""}
            {poi.image_attribution.source_url && (
              <> · <a href={poi.image_attribution.source_url} target="_blank" rel="noopener noreferrer" className="underline">source</a></>
            )}
          </p>
        )}

        <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <CategoryBadge category={poi.category} />
              {poi.secondary_categories.slice(0, 2).map((c) => <Badge key={c}>{categoryMeta(c).label}</Badge>)}
              {poi.estimated_cost.max === 0 && <Badge tone="success">Free</Badge>}
              {poi.recommended_as_primary_destination && <Badge tone="info">Worth a day trip</Badge>}
            </div>
            <h1 className="mt-3 font-display text-3xl font-semibold tracking-tight sm:text-headline">{poi.name}</h1>
            <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-muted-foreground">
              <span className="inline-flex items-center gap-1.5"><MapPin className="size-4" aria-hidden="true" />{[poi.locality, poi.district].filter(Boolean).join(", ") || regionLabel(poi.region_bucket)}</span>
              <span className="inline-flex items-center gap-1.5"><Ruler className="size-4" aria-hidden="true" />{distanceLabel(poi.distance_from_center_km)}</span>
            </p>
            {poi.short_description && <p className="mt-4 text-lg leading-relaxed text-foreground/85">{poi.short_description}</p>}

            <div className="mt-5 flex flex-wrap gap-2">
              <SaveButton poi={poi} variant="pill" />
              <Button variant="primary" onClick={() => void navigate({ to: "/plans/new", search: { include: poi.id } })}>
                <CalendarPlus aria-hidden="true" /> Plan a day around this
              </Button>
              <Button variant="secondary" onClick={() => void navigate({ to: "/ask", search: { q: `Tell me about ${poi.name}`, new: true } })}>
                <Sparkles aria-hidden="true" /> Ask about it
              </Button>
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <Fact icon={<Wallet aria-hidden="true" />} label="Estimated cost" value={costLabel(poi.estimated_cost)} hint="per person · NavigIQ estimate" />
              <Fact icon={<Clock3 aria-hidden="true" />} label="Typical visit" value={minutesLabel(poi.visit_duration.typical)} hint={`${minutesLabel(poi.visit_duration.min)}–${minutesLabel(poi.visit_duration.max)}`} />
              <Fact icon={<meta.icon aria-hidden="true" />} label="Setting" value={humanize(poi.indoor_outdoor)} hint={poi.is_chain ? "Part of a chain" : undefined} />
            </div>

            {poi.description && (
              <section className="mt-8">
                <h2 className="font-display text-xl font-semibold">About</h2>
                <p className="mt-2 whitespace-pre-line leading-relaxed text-foreground/85">{poi.description}</p>
                {poi.description_source && (
                  <p className="mt-2 text-xs text-muted-foreground">Description from {poi.description_source === "wikipedia" ? "Wikipedia (CC BY-SA)" : humanize(poi.description_source)}.</p>
                )}
              </section>
            )}

            {(tags.length > 0 || suits.length > 0 || poi.accessibility_tags.length > 0 || poi.dietary_tags.length > 0) && (
              <section className="mt-8">
                <h2 className="font-display text-xl font-semibold">Good to know</h2>
                {tags.length > 0 && (
                  <div className="mt-3">
                    <p className="text-sm font-medium text-muted-foreground">Known for</p>
                    <ul className="mt-1.5 flex flex-wrap gap-1.5">
                      {tags.map((t) => <li key={t}><Badge>{humanize(t)}</Badge></li>)}
                    </ul>
                  </div>
                )}
                {suits.length > 0 && (
                  <div className="mt-3">
                    <p className="text-sm font-medium text-muted-foreground">Suits</p>
                    <ul className="mt-1.5 flex flex-wrap gap-1.5">
                      {suits.map((s) => <li key={s.key}><Badge tone="primary"><Check aria-hidden="true" />{s.label}</Badge></li>)}
                    </ul>
                  </div>
                )}
                {poi.dietary_tags.length > 0 && (
                  <div className="mt-3">
                    <p className="text-sm font-medium text-muted-foreground">Food</p>
                    <ul className="mt-1.5 flex flex-wrap gap-1.5">
                      {poi.dietary_tags.map((t) => <li key={t}><Badge tone="success">{humanize(t)}</Badge></li>)}
                    </ul>
                  </div>
                )}
                {poi.accessibility_tags.length > 0 && (
                  <div className="mt-3">
                    <p className="text-sm font-medium text-muted-foreground">Accessibility</p>
                    <ul className="mt-1.5 flex flex-wrap gap-1.5">
                      {poi.accessibility_tags.map((t) => <li key={t}><Badge tone="info">{humanize(t)}</Badge></li>)}
                    </ul>
                  </div>
                )}
              </section>
            )}
          </div>

          <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start" aria-label="Location and hours">
            <div className="overflow-hidden rounded-3xl ring-1 ring-border/60">
              <LazyMap label={`Map showing ${poi.name}`} className="h-56" pins={[{ id: poi.id, lat: poi.lat, lon: poi.lon, title: poi.name }]} />
              <div className="bg-card p-4">
                {poi.address && <p className="text-sm text-foreground/80">{poi.address}</p>}
                <a
                  href={externalMapUrl(poi.lat, poi.lon)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:underline"
                >
                  Open in OpenStreetMap <ExternalLink className="size-3.5" aria-hidden="true" />
                  <span className="sr-only">(external site, opens in a new tab)</span>
                </a>
                <p className="mt-1 text-xs text-muted-foreground">External map. NavigIQ doesn't calculate routes or travel times.</p>
              </div>
            </div>
            <Hours poi={poi} />
            {poi.attribution?.length > 0 && (
              <section className="rounded-3xl bg-card p-5 ring-1 ring-border/60">
                <h2 className="text-sm font-semibold">Where this comes from</h2>
                <ul className="mt-2 space-y-1.5 text-sm">
                  {poi.attribution.map((a) => (
                    <li key={a.name + (a.url ?? "")}>
                      {a.url ? (
                        <a href={a.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 hover:underline">
                          {a.name} <ExternalLink className="size-3" aria-hidden="true" />
                        </a>
                      ) : a.name}
                      {a.license && <span className="ml-1.5 text-xs text-muted-foreground">{a.license}</span>}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </aside>
        </div>

        {(similar.data?.items.length ?? 0) > 0 && (
          <section className="mt-12" aria-labelledby="similar-title">
            <SectionHeader id="similar-title" title="Similar in feel" description="Ranked by what this place is like — category, mood and setting." />
            <PoiRail label="Similar places" items={similar.data?.items} loading={similar.isPending} />
          </section>
        )}
      </main>
      <PageFooter />
    </>
  );
}
