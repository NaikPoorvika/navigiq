import { useEffect, useState } from "react";
import { ArrowRight, Loader2, MapPin, Sparkles, X } from "lucide-react";
import { resolvePlace } from "../api/client";
import PreviewBadge from "../components/PreviewBadge";
import { categoryIcon, categoryLabel } from "../lib/categories";
import { CENTRAL, specFromProfile } from "../lib/defaults";
import { understand, type Understood } from "../lib/preview-parser";
import { navigate } from "../lib/router";
import { useAccount } from "../store/account";
import { setPendingPlan } from "../store/pending";
import type { Place } from "../types";

const SUGGESTIONS = [
  "A quiet café and a park near Indiranagar this evening",
  "Historic places and lunch in Basavanagudi",
  "Street food and dessert near Jayanagar tonight",
  "A lake at sunset, then dinner, for 2",
];

export default function DiscoverPage({ initialQuery }: { initialQuery: string }) {
  const { profile } = useAccount();
  const [text, setText] = useState(initialQuery);
  const [result, setResult] = useState<Understood | null>(null);
  const [origin, setOrigin] = useState<Place | null>(null);
  const [originNote, setOriginNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(q: string) {
    if (!q.trim()) return;
    setBusy(true);
    const u = understand(q);
    let place: Place = profile?.home ?? CENTRAL;
    let note = profile?.home ? `From your home, ${place.name}` : "From central Bengaluru";
    if (u.place) {
      try {
        const r = await resolvePlace(u.place);
        if (r.match && !r.needs_clarification) {
          place = { name: r.match.name, lat: r.match.lat, lon: r.match.lon };
          note = `From ${r.match.name}`;
        } else if (r.match) {
          note = `"${u.place}" matches more than one place — pick it on the planner`;
        } else {
          note = `Couldn't find "${u.place}" — using ${place.name}`;
        }
      } catch {
        note = `Couldn't look up "${u.place}" — using ${place.name}`;
      }
    }
    setOrigin(place);
    setOriginNote(note);
    setResult(u);
    setBusy(false);
  }

  useEffect(() => {
    if (initialQuery) void run(initialQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function removeInterest(category: string) {
    if (result) setResult({ ...result, interests: result.interests.filter((i) => i.category !== category) });
  }

  function planIt(auto: boolean) {
    if (!result || !origin) return;
    setPendingPlan(
      specFromProfile(profile, {
        origin,
        interests: result.interests,
        ...(result.start ? { start_time_local: result.start } : {}),
        ...(result.end ? { end_time_local: result.end } : {}),
        ...(result.budget ? { budget_inr: result.budget } : {}),
        ...(result.party ? { party_size: result.party } : {}),
        constraints: {
          max_walking_km: 2, meal_required: true,
          vegetarian: result.vegetarian || (profile?.vegetarian ?? false),
        },
      }),
      auto && result.interests.length > 0,
    );
    navigate("/plan");
  }

  return (
    <div className="discover">
      <section className="discover-head">
        <span className="eyebrow"><Sparkles size={14} aria-hidden="true" /> Plan with AI</span>
        <h1>Describe your trip in your own words</h1>
        <p className="muted">
          <PreviewBadge reason="The language model arrives with NQ-029. This preview uses keyword matching." />{" "}
          This preview uses simple keyword matching. The AI version will understand much more — and will
          ask when something is unclear.
        </p>

        <form className="ask-box" onSubmit={(e) => { e.preventDefault(); void run(text); }}>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            placeholder="e.g. A historic place and a good lunch near Basavanagudi this afternoon, under ₹1000"
            aria-label="Describe your trip"
          />
          <button type="submit" className="primary" disabled={busy || !text.trim()}>
            {busy ? <><Loader2 className="spin" size={18} /> Reading…</> : <><Sparkles size={18} /> Understand</>}
          </button>
        </form>

        <div className="chips">
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" className="chip" onClick={() => { setText(s); void run(s); }}>{s}</button>
          ))}
        </div>
      </section>

      {result && (
        <section className="card understood step-enter">
          <h2>Here's what I picked up</h2>
          <p className="muted"><MapPin size={14} aria-hidden="true" /> {originNote}</p>

          {result.interests.length === 0 ? (
            <p className="warn">I didn't catch anything to do. Try naming a few things — cafés, parks, a museum.</p>
          ) : (
            <div className="chips">
              {result.interests.map((i) => {
                const Icon = categoryIcon(i.category);
                return (
                  <span key={i.category} className="chip on">
                    <Icon size={15} aria-hidden="true" /> {categoryLabel(i.category)}
                    {i.priority === "must" && <small> · must</small>}
                    <button type="button" className="chip-x" aria-label={`Remove ${i.category}`} onClick={() => removeInterest(i.category)}>
                      <X size={13} />
                    </button>
                  </span>
                );
              })}
            </div>
          )}

          <ul className="understood-facts">
            <li><strong>Time:</strong> {result.start && result.end ? `${result.start}–${result.end}` : "not mentioned — defaults to 15:00–20:00"}</li>
            <li><strong>Budget:</strong> {result.budget ? `₹${result.budget}` : "not mentioned"}</li>
            <li><strong>People:</strong> {result.party ?? "not mentioned — 1"}</li>
            {result.vegetarian && <li><strong>Food:</strong> vegetarian</li>}
          </ul>

          <div className="understood-actions">
            <button type="button" className="primary" disabled={result.interests.length === 0} onClick={() => planIt(true)}>
              Plan this <ArrowRight size={17} />
            </button>
            <button type="button" className="btn-outline" onClick={() => planIt(false)}>Adjust in the planner</button>
          </div>
        </section>
      )}
    </div>
  );
}
