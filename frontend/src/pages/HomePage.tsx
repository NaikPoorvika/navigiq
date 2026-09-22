import { useEffect, useState } from "react";
import { ArrowRight, CalendarDays, Compass, MapPin, Search, Sparkles } from "lucide-react";
import { getCategories, searchPois } from "../api/client";
import CategoryPhoto from "../components/CategoryPhoto";
import PoiCard from "../components/PoiCard";
import { categoryLabel } from "../lib/categories";
import { CENTRAL, specFromProfile } from "../lib/defaults";
import { PLAN_IDEAS, type PlanIdea } from "../lib/ideas";
import { href, navigate } from "../lib/router";
import { formatDate, greeting } from "../lib/time";
import { useAccount } from "../store/account";
import { setPendingPlan } from "../store/pending";
import { useSavedPlans } from "../store/plans";
import type { Category, PoiSummary } from "../types";

export default function HomePage() {
  const { profile } = useAccount();
  const home = profile?.home ?? CENTRAL;
  const interests = profile?.interests ?? [];
  const plans = useSavedPlans();

  const [nearby, setNearby] = useState<PoiSummary[] | null>(null);
  const [nearbyFailed, setNearbyFailed] = useState(false);
  const [categories, setCategories] = useState<Category[]>([]);
  const [query, setQuery] = useState("");

  const interestKey = interests.join(",");
  useEffect(() => {
    setNearby(null);
    setNearbyFailed(false);
    searchPois({ lat: home.lat, lon: home.lon, radiusKm: 3, categories: interests.slice(0, 4), limit: 8 })
      .then((r) => setNearby(r.results))
      .catch(() => setNearbyFailed(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [home.lat, home.lon, interestKey]);

  useEffect(() => {
    getCategories().then((r) => setCategories(r.categories)).catch(() => setCategories([]));
  }, []);

  function planIdea(idea: PlanIdea) {
    setPendingPlan(
      specFromProfile(profile, {
        interests: idea.interests, start_time_local: idea.start,
        end_time_local: idea.end, mode: idea.mode,
      }),
      Boolean(profile?.home),
    );
    navigate("/plan");
  }

  function planCategory(key: string) {
    setPendingPlan(specFromProfile(profile, { interests: [{ category: key, count: 1, priority: "must" }] }));
    navigate("/plan");
  }

  const heroCategory = interests[0] ?? "park";

  return (
    <div className="home">
      <section className="home-hero">
        <CategoryPhoto
          category={heroCategory}
          fallbacks={[...interests, "park", "lake", "historical", "temple", "museum", "landmark"]}
          variant="tile"
        />
        <span className="hero-overlay" aria-hidden="true" />
        <span className="hero-eyebrow">
          {greeting()}{profile ? `, ${profile.name.split(" ")[0]}` : ""}
        </span>
        <h1>Where to today?</h1>
        <p>
          <MapPin size={15} aria-hidden="true" />{" "}
          {profile?.home ? `From ${home.name}` : "Set your neighbourhood to plan from home"}
        </p>
        <div className="hero-actions">
          <button type="button" className="btn-light"
                  onClick={() => { setPendingPlan(specFromProfile(profile)); navigate("/plan"); }}>
            <CalendarDays size={16} aria-hidden="true" /> Plan my day
          </button>
          {!profile && <a className="btn-ghost" href={href("/welcome")}>Personalise NavigIQ <ArrowRight size={15} /></a>}
        </div>

        <form
          className="ask-bar"
          onSubmit={(e) => {
            e.preventDefault();
            navigate(`/discover?q=${encodeURIComponent(query.trim())}`);
          }}
        >
          <Sparkles size={18} aria-hidden="true" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Try: a quiet café and a park near Indiranagar this evening"
            aria-label="Describe your trip"
          />
          <button type="submit" aria-label="Plan with AI"><ArrowRight size={18} /></button>
        </form>
      </section>

      <section className="home-section">
        <div className="section-head">
          <div>
            <h2>Near {profile?.home ? "you" : "the city centre"}</h2>
            <p>{interests.length ? "Matching your interests, within 3 km." : "Within 3 km."}</p>
          </div>
        </div>
        {nearbyFailed && <p className="field-error">Couldn't load nearby places — is the backend running?</p>}
        {!nearbyFailed && nearby === null && <div className="card-row">{[0, 1, 2, 3].map((i) => <div key={i} className="poi-card skeleton" />)}</div>}
        {nearby && nearby.length === 0 && <p className="muted">Nothing within 3 km for these interests.</p>}
        {nearby && nearby.length > 0 && (
          <div className="card-row">{nearby.map((p) => <PoiCard key={p.id} poi={p} />)}</div>
        )}
      </section>

      <section className="home-section">
        <div className="section-head">
          <div>
            <h2>Plan ideas</h2>
            <p>Ready-made requests — each one builds a real plan from your starting point.</p>
          </div>
        </div>
        <div className="idea-grid">
          {PLAN_IDEAS.map((idea) => (
            <button key={idea.id} type="button" className="idea-card" onClick={() => planIdea(idea)}>
              <CategoryPhoto
                category={idea.cover}
                fallbacks={idea.interests.map((i) => i.category)}
                variant="tile"
                showCredit={false}
              />
              <span className="idea-shade" />
              <span className="idea-text">
                <strong>{idea.title}</strong>
                <span>{idea.blurb}</span>
                <span className="idea-go">{idea.start}–{idea.end} <ArrowRight size={15} aria-hidden="true" /></span>
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="home-section">
        <div className="section-head">
          <div>
            <h2>Explore by category</h2>
            <p>Counts are real places in the NavigIQ database.</p>
          </div>
        </div>
        <div className="category-grid">
          {categories.filter((c) => c.poi_count > 0).map((c) => (
            <button key={c.key} type="button" className="category-tile" onClick={() => planCategory(c.key)}>
              <CategoryPhoto category={c.key} variant="thumb" showCredit={false} />
              <span>
                <strong>{c.display_name || categoryLabel(c.key)}</strong>
                <span className="muted">{c.poi_count.toLocaleString("en-IN")} places</span>
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="home-section">
        <div className="section-head">
          <div>
            <h2>Your plans</h2>
            <p>Saved in this browser.</p>
          </div>
          {plans.length > 3 && <a className="link" href={href("/plans")}>See all</a>}
        </div>
        {plans.length === 0 ? (
          <div className="empty-inline">
            <Compass size={20} aria-hidden="true" />
            <span>Plans you make will appear here. <a href={href("/plan")}>Plan one now</a></span>
          </div>
        ) : (
          <div className="plan-grid">
            {plans.slice(0, 3).map((p) => (
              <a key={p.id} className="plan-card" href={href(`/plans/${p.id}`)}>
                <span className="plan-date"><CalendarDays size={14} aria-hidden="true" /> {formatDate(p.spec.date)}</span>
                <strong>From {p.spec.origin.name ?? "your start"}</strong>
                <span className="plan-stops">{p.data.itinerary.stops.map((s) => s.name).join(" → ")}</span>
                <span className="muted">{p.data.itinerary.stops.length} stops · {p.spec.start_time_local}–{p.spec.end_time_local}</span>
              </a>
            ))}
          </div>
        )}
      </section>

      <section className="home-section">
        <a className="search-strip" href={href("/plan")}>
          <Search size={18} aria-hidden="true" /> Know what you want? Build a plan step by step <ArrowRight size={16} aria-hidden="true" />
        </a>
      </section>
    </div>
  );
}
