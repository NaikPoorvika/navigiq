/**
 * Explore home. Everything personal or "right now" on this screen comes from
 * real data: the server's IST clock, the live forecast (or nothing), the
 * ranking engine's reasons, the person's own plans and saved places.
 */
import { Link, useNavigate } from "@tanstack/react-router";
import {
  ArrowRight, CalendarPlus, CloudRain, Dices, Heart, IndianRupee, Leaf, MountainSnow,
  Sparkles, Sun, UtensilsCrossed, WandSparkles,
} from "lucide-react";
import { useMemo, useState } from "react";
import { AskBar } from "@/components/ask/AskBar";
import { PageFooter } from "@/components/layout/AppShell";
import { PlanStrip } from "@/components/plan/PlanStrip";
import { CategoryArt } from "@/components/poi/PoiArt";
import { PoiRail } from "@/components/poi/PoiRail";
import { Button } from "@/components/ui/button";
import { Chip, ErrorState, SectionHeader } from "@/components/ui/primitives";
import type { HomeContext } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { GROUP_TONE } from "@/lib/categories";
import { cn } from "@/lib/cn";
import { GROUP_CATEGORY, collectionLook } from "@/lib/collections";
import { useDocumentTitle } from "@/lib/hooks";
import { heroArt } from "@/lib/media";
import { useCollections, useHomeContext, usePlans, usePreferences, useRecommend } from "@/lib/queries";
import { recentPrompts, rememberPrompt } from "@/lib/recent";

const GREETING: Record<HomeContext["time_of_day"], string> = {
  morning: "morning", afternoon: "afternoon", evening: "evening", night: "night",
};

function contextLine(ctx: HomeContext | undefined): string | null {
  if (!ctx) return null;
  const when = `${ctx.weekday} ${GREETING[ctx.time_of_day]} in Bengaluru`;
  const w = ctx.weather;
  if (!w.available) return when;
  const temp = w.mean_temp_c !== null ? `${Math.round(w.mean_temp_c)}°C` : null;
  const sky = w.heavy_rain_expected ? "heavy rain expected" : w.rain_likely ? "rain likely" : w.condition === "light_rain" ? "a little rain" : "dry";
  return [when, [temp, sky].filter(Boolean).join(", ")].filter(Boolean).join(" · ");
}

const INTENTS = [
  { label: "I'm bored", icon: Dices, to: "/bored" as const, tone: "accent" as const },
  { label: "Surprise me", icon: WandSparkles, to: "/bored" as const, search: { surprise: true }, tone: "accent" as const },
  { label: "Date ideas", icon: Heart, collection: "romantic" },
  { label: "Nature", icon: Leaf, collection: "nature_escapes" },
  { label: "Food", icon: UtensilsCrossed, collection: "food" },
  { label: "Under ₹500", icon: IndianRupee, collection: "under_500" },
  { label: "Weekend escape", icon: MountainSnow, collection: "weekend_escapes" },
];

function Hero({ ctx, onAsk }: { ctx: HomeContext | undefined; onAsk: (t: string) => void }) {
  const art = heroArt(ctx?.time_of_day, Boolean(ctx?.weather.rain_likely || ctx?.weather.heavy_rain_expected));
  const line = contextLine(ctx);
  const navigate = useNavigate();
  const [recent] = useState(() => recentPrompts());

  return (
    <section aria-labelledby="hero-title" className="relative isolate overflow-hidden bg-olive-900">
      <img
        src={art.src}
        alt={art.alt}
        className="absolute inset-0 -z-20 size-full object-cover opacity-90"
        fetchPriority="high"
        decoding="async"
      />
      <div className="absolute inset-0 -z-10 bg-gradient-to-b from-olive-950/70 via-olive-950/45 to-olive-950/85" aria-hidden="true" />
      <div className="mx-auto flex min-h-[40rem] max-w-page flex-col justify-end px-4 pb-10 pt-28 sm:min-h-[44rem] sm:px-6 sm:pb-14 lg:px-8">
        <div className="max-w-3xl animate-rise">
          {line && (
            <p className="mb-4 inline-flex items-center gap-2 rounded-full bg-white/12 px-3.5 py-1.5 text-sm font-medium text-white/90 backdrop-blur-sm">
              {ctx?.weather.rain_likely ? <CloudRain className="size-4" aria-hidden="true" /> : <Sun className="size-4" aria-hidden="true" />}
              {line}
            </p>
          )}
          <h1 id="hero-title" className="font-display text-[2.6rem] font-semibold leading-[1.02] tracking-[-0.035em] text-white sm:text-display">
            What's your mood today?
          </h1>
          <p className="mt-4 max-w-xl text-base text-white/80 sm:text-lg">
            Tell NavigIQ what you feel like. It finds places across Bengaluru and 90 km around,
            says why they fit, and plans the day around opening hours and your budget.
          </p>
          <AskBar variant="hero" onSubmit={onAsk} className="mt-7 max-w-2xl" label="Ask NavigIQ anything about Bengaluru" />
          <div className="mt-5 flex flex-wrap gap-2" aria-label="Quick ideas">
            {INTENTS.map((it) => {
              const Icon = it.icon;
              const go = () => {
                if ("collection" in it && it.collection) void navigate({ to: "/collections/$collectionId", params: { collectionId: it.collection } });
                else if (it.to) void navigate({ to: it.to, search: "search" in it ? it.search : undefined });
              };
              return (
                <button
                  key={it.label}
                  type="button"
                  onClick={go}
                  className={cn(
                    "inline-flex h-10 items-center gap-2 rounded-full px-4 text-sm font-semibold backdrop-blur-md transition-[background-color,transform] active:scale-[0.97]",
                    it.tone === "accent" ? "bg-clay-500/90 text-white hover:bg-clay-500" : "bg-white/14 text-white ring-1 ring-white/20 hover:bg-white/22",
                  )}
                >
                  <Icon className="size-4" aria-hidden="true" />
                  {it.label}
                </button>
              );
            })}
          </div>
          {recent.length > 0 && (
            <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-white/70">
              <span>Recently asked:</span>
              {recent.slice(0, 3).map((p) => (
                <button key={p} type="button" onClick={() => onAsk(p)} className="max-w-[16rem] truncate rounded underline decoration-white/30 underline-offset-4 hover:text-white">
                  {p}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <span className="absolute bottom-3 right-4 text-[10px] font-medium uppercase tracking-wider text-white/45">Illustration</span>
    </section>
  );
}

const MOMENT: Record<HomeContext["time_of_day"], { title: string; moods: string[] }> = {
  morning: { title: "Good for this morning", moods: ["peaceful", "nature"] },
  afternoon: { title: "Good for this afternoon", moods: ["cultural", "relaxing"] },
  evening: { title: "Good for this evening", moods: ["scenic", "foodie"] },
  night: { title: "Good for tonight", moods: ["foodie", "social"] },
};

function RightNow({ ctx, ready }: { ctx: HomeContext | undefined; ready: boolean }) {
  const tod = ctx?.time_of_day ?? "afternoon";
  const rain = Boolean(ctx?.weather.available && (ctx.weather.rain_likely || ctx.weather.heavy_rain_expected));
  const moment = MOMENT[tod];
  const q = useRecommend({
    moods: rain ? ["relaxing"] : moment.moods,
    indoor_preference: rain ? "indoor" : undefined,
    rain_expected: ctx?.weather.available ? rain : undefined,
    scope: "city",
    limit: 10,
  }, ready);
  return (
    <section aria-labelledby="now-title">
      <SectionHeader
        id="now-title"
        eyebrow={rain ? "Rain is likely" : "Right now"}
        title={rain ? "Indoor ideas for a wet day" : moment.title}
        description={rain
          ? "Today's forecast says rain, so these lean indoors."
          : "Picked for the time of day in Bengaluru. Each card says why."}
        action={<Button asChild variant="ghost" size="sm"><Link to="/search">See more <ArrowRight aria-hidden="true" /></Link></Button>}
      />
      {q.isError ? (
        <ErrorState description="The recommendations didn't load." onRetry={() => void q.refetch()} />
      ) : (
        <PoiRail label={rain ? "Indoor ideas" : moment.title} items={q.data?.items} loading={q.isPending} />
      )}
    </section>
  );
}

function ForYou() {
  const prefs = usePreferences();
  const hasPrefs = Boolean(prefs.data && (prefs.data.favorite_categories.length || prefs.data.favorite_moods.length));
  const q = useRecommend({ mode: "for_you", limit: 10 }, hasPrefs);
  if (!hasPrefs || q.isError || (q.data && q.data.items.length === 0)) return null;
  return (
    <section aria-labelledby="foryou-title">
      <SectionHeader id="foryou-title" eyebrow="For you" title="Picked from your taste"
        description="Based on the categories and moods in your profile, and what you've saved." />
      <PoiRail label="For you" items={q.data?.items} loading={q.isPending} />
    </section>
  );
}

const RAILS = [
  { id: "something_different", eyebrow: "Something different", title: "Off the usual list" },
  { id: "weekend_escapes", eyebrow: "Around Bengaluru", title: "Weekend escapes" },
  { id: "food", eyebrow: "Food & cafés", title: "Where to eat and linger" },
  { id: "top_picks", eyebrow: "Things to do", title: "Bengaluru essentials" },
];

function CollectionRails() {
  const q = useCollections(RAILS.map((r) => r.id));
  const byId = useMemo(() => new Map((q.data?.collections ?? []).map((c) => [c.id, c])), [q.data]);
  if (q.isError) return <ErrorState description="Collections didn't load." onRetry={() => void q.refetch()} />;
  return (
    <>
      {RAILS.map((r) => {
        const c = byId.get(r.id);
        if (!q.isPending && (!c || c.items.length === 0)) return null;
        return (
          <section key={r.id} aria-labelledby={`rail-${r.id}`}>
            <SectionHeader
              id={`rail-${r.id}`}
              eyebrow={r.eyebrow}
              title={c?.title && r.id !== "food" ? c.title : r.title}
              description={c?.subtitle ?? undefined}
              action={<Button asChild variant="ghost" size="sm"><Link to="/collections/$collectionId" params={{ collectionId: r.id }}>All <ArrowRight aria-hidden="true" /></Link></Button>}
            />
            <PoiRail label={r.title} items={c?.items} loading={q.isPending} />
          </section>
        );
      })}
    </>
  );
}

function CollectionTiles() {
  const q = useCollections();
  const available = (q.data?.available ?? []).filter((c) => !["for_you", "top_picks", "something_different", "weekend_escapes", "food"].includes(c.id));
  if (!available.length) return null;
  return (
    <section aria-labelledby="tiles-title">
      <SectionHeader id="tiles-title" eyebrow="Collections" title="Browse by mood"
        action={<Button asChild variant="ghost" size="sm"><Link to="/collections">All collections <ArrowRight aria-hidden="true" /></Link></Button>} />
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {available.slice(0, 8).map((c) => {
          const look = collectionLook(c.id);
          const tone = GROUP_TONE[look.group];
          return (
            <li key={c.id}>
              <Link
                to="/collections/$collectionId"
                params={{ collectionId: c.id }}
                className="group relative block h-40 overflow-hidden rounded-3xl shadow-soft ring-1 ring-border/50 sm:h-48"
              >
                {look.art ? (
                  <>
                    <img src={look.art.src} alt="" loading="lazy" className="absolute inset-0 size-full object-cover transition-transform duration-500 group-hover:scale-[1.04]" />
                    <div className="absolute inset-0 bg-gradient-to-t from-olive-950/85 via-olive-950/25 to-transparent" aria-hidden="true" />
                  </>
                ) : (
                  <>
                    <CategoryArt category={GROUP_CATEGORY[look.group] ?? "neighborhood"} seed={c.id} className="absolute inset-0 size-full" iconSize="lg" />
                    <div className="absolute inset-x-0 bottom-0 h-3/5 bg-gradient-to-t from-card via-card/85 to-transparent" aria-hidden="true" />
                  </>
                )}
                <div className={cn("absolute inset-x-0 bottom-0 p-4", look.art ? "text-white" : tone.ink)}>
                  <p className="font-display text-base font-semibold leading-tight sm:text-lg">{c.title}</p>
                  {c.subtitle && <p className={cn("mt-1 line-clamp-2 text-xs", look.art ? "text-white/80" : "opacity-80")}>{c.subtitle}</p>}
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function YourPlans() {
  const q = usePlans();
  const plans = q.data?.plans ?? [];
  if (!plans.length) return null;
  return (
    <section aria-labelledby="plans-title">
      <SectionHeader id="plans-title" eyebrow="Pick up where you left off" title="Your plans"
        action={<Button asChild variant="ghost" size="sm"><Link to="/plans">All plans <ArrowRight aria-hidden="true" /></Link></Button>} />
      <PlanStrip plans={plans.slice(0, 3)} />
    </section>
  );
}

function PlanCta() {
  return (
    <section className="relative overflow-hidden rounded-[2rem] bg-primary px-6 py-10 text-primary-foreground sm:px-10 sm:py-12">
      <div className="absolute -right-16 -top-20 size-72 rounded-full bg-olive-500/40 blur-3xl" aria-hidden="true" />
      <div className="relative max-w-2xl">
        <p className="text-sm font-semibold uppercase tracking-[0.14em] text-sand-300">Plan</p>
        <h2 className="mt-2 font-display text-3xl font-semibold tracking-tight sm:text-4xl">Turn a mood into a whole day — or a long weekend</h2>
        <p className="mt-3 text-primary-foreground/80">
          Pick interests, a budget and the hours you have. NavigIQ checks opening times, keeps you
          within budget, spaces the stops out and never repeats a place across days.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Button asChild variant="secondary" size="lg">
            <Link to="/plans/new"><CalendarPlus aria-hidden="true" /> Plan a day</Link>
          </Button>
          <Button asChild variant="ghost" size="lg" className="text-primary-foreground hover:bg-white/10">
            <Link to="/plans/new" search={{ days: 2 }}><Sparkles aria-hidden="true" /> Plan a weekend</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

export function HomePage() {
  useDocumentTitle("Explore Bengaluru");
  const ctx = useHomeContext();
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const ask = (text: string) => {
    rememberPrompt(text);
    void navigate({ to: "/ask", search: { q: text, new: true } });
  };
  return (
    <>
      <Hero ctx={ctx.data} onAsk={ask} />
      <main id="main" className="mx-auto max-w-page space-y-14 px-4 pt-12 sm:px-6 sm:pt-14 lg:px-8">
        {isAuthenticated && <ForYou />}
        <RightNow ctx={ctx.data} ready={!ctx.isPending} />
        <YourPlans />
        <CollectionRails />
        <CollectionTiles />
        <PlanCta />
        <div className="flex flex-wrap items-center gap-2" aria-label="More ways to explore">
          <span className="mr-1 text-sm text-muted-foreground">Or browse:</span>
          <Chip onClick={() => void navigate({ to: "/search", search: { category: ["museum"] } })}>Museums</Chip>
          <Chip onClick={() => void navigate({ to: "/search", search: { category: ["lake"] } })}>Lakes</Chip>
          <Chip onClick={() => void navigate({ to: "/search", search: { category: ["temple"] } })}>Temples</Chip>
          <Chip onClick={() => void navigate({ to: "/search", search: { category: ["market"] } })}>Markets</Chip>
          <Chip onClick={() => void navigate({ to: "/search", search: { scope: "regional" } })}>Beyond the city</Chip>
        </div>
      </main>
      <PageFooter />
    </>
  );
}
