import { useEffect, useState } from "react";
import {
  AlertTriangle, ArrowRight, CalendarDays, Clock, Info, Loader2, Sparkles, Wallet,
} from "lucide-react";
import { buildDraft, extractDraft, getCategories, PlanError, resolvePlace } from "../api/client";
import InterestPicker from "../components/InterestPicker";
import PlaceSearch from "../components/PlaceSearch";
import { specFromProfile } from "../lib/defaults";
import { interestsFromWords } from "../lib/keyword-interests";
import { navigate } from "../lib/router";
import { localDate } from "../lib/time";
import { useAccount } from "../store/account";
import { setPendingPlan } from "../store/pending";
import type { Category, Extraction, Interest, Place, TripDraft } from "../types";

const SUGGESTIONS = [
  "A quiet café and a park near Indiranagar this evening",
  "Historic places and lunch in Basavanagudi, under ₹1000",
  "Street food and dessert near Jayanagar tonight for 3",
  "A lake at sunset then dinner, vegetarian, from Koramangala",
];

/** The model reads a sentence; everything it proposes is shown and editable. */
export default function DiscoverPage({ initialQuery }: { initialQuery: string }) {
  const { profile } = useAccount();
  const [text, setText] = useState(initialQuery);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [assumptions, setAssumptions] = useState<string[]>([]);
  const [questions, setQuestions] = useState<string[]>([]);
  const [guessedInterests, setGuessedInterests] = useState(false);

  // The proposal, after the user has corrected it.
  const [origin, setOrigin] = useState<Place | null>(null);
  const [originAsked, setOriginAsked] = useState<string | null>(null);
  const [date, setDate] = useState(localDate());
  const [start, setStart] = useState("15:00");
  const [end, setEnd] = useState("20:00");
  const [interests, setInterests] = useState<Interest[]>([]);
  const [budget, setBudget] = useState("");
  const [party, setParty] = useState(1);
  const [vegetarian, setVegetarian] = useState(false);

  useEffect(() => {
    getCategories().then((r) => setCategories(r.categories)).catch(() => setCategories([]));
  }, []);
  /** Fill the form from the draft.
   *
   *  The server resolves it first (dry run): "tonight" becomes a date and a
   *  time window, defaults are applied, and anything ambiguous comes back as
   *  a question. Only a place the gazetteer could not settle is left for the
   *  user to pick here.
   */
  async function applyDraft(draft: TripDraft, requestText: string) {
    // A small model sometimes returns no interests for a sentence that
    // plainly has them. Match the words against real categories rather
    // than asking about something already said.
    let chosen: Interest[] = draft.interests.map((i) => ({
      category: i.category, count: i.count, priority: i.priority,
    }));
    const guessed = chosen.length === 0;
    if (guessed) chosen = interestsFromWords(requestText, categories);
    setGuessedInterests(guessed && chosen.length > 0);
    setInterests(chosen);
    setOrigin(null);
    setOriginAsked(null);
    setAssumptions([]);
    setQuestions([]);

    let built = null;
    try {
      built = await buildDraft(draft);
    } catch {
      /* fall back to the raw draft below */
    }

    // Times and dates come from the server whether or not the draft was
    // complete - otherwise the screen shows "Starting at 18:00" above a
    // field reading 15:00.
    const r = built?.resolved;
    if (r?.date) setDate(r.date);
    if (r?.start_time_local) setStart(r.start_time_local);
    if (r?.end_time_local) setEnd(r.end_time_local);
    if (r?.party_size) setParty(r.party_size);
    if (r?.budget_inr != null) setBudget(String(r.budget_inr));
    if (r?.vegetarian) setVegetarian(true);

    if (built?.tripspec) {
      const s = built.tripspec;
      setOrigin(s.origin);
      setDate(s.date);
      setStart(s.start_time_local);
      setEnd(s.end_time_local);
      setParty(s.party_size);
      setBudget(s.budget_inr != null ? String(s.budget_inr) : "");
      setVegetarian(Boolean(s.constraints.vegetarian));
      if (s.interests.length > 0) { setInterests(s.interests); setGuessedInterests(false); }
      setAssumptions(built.assumptions);
      return;
    }

    setAssumptions(built?.assumptions ?? []);
    setQuestions((built?.clarifications ?? [])
      .filter((c) => c.field !== "origin")
      .map((c) => c.question));

    // Times and party size the server could not settle.
    if (draft.start_time_local) setStart(draft.start_time_local);
    if (draft.end_time_local) setEnd(draft.end_time_local);
    if (draft.budget_inr) setBudget(String(draft.budget_inr));
    if (draft.party_size) setParty(draft.party_size);
    if (draft.vegetarian) setVegetarian(true);

    const originQuestion = (built?.clarifications ?? [])
      .find((c) => c.field === "origin")?.question;
    const name = draft.origin?.name ?? profile?.home?.name ?? null;
    // "near me", "from here" - a real request, but not a place the gazetteer
    // can find. Point at the button that can answer it.
    if (name && /^(me|here|my location|current location|nearby|around me)$/i.test(name.trim())) {
      setOriginAsked("Press “Use my location” below, or type where you'll be starting from.");
      return;
    }
    if (originQuestion) {
      setOriginAsked(originQuestion);
      return;
    }
    if (!name) {
      setOriginAsked("Where will you be starting from?");
      return;
    }
    try {
      const r = await resolvePlace(name);
      if (r.match && !r.needs_clarification) {
        setOrigin({ name: r.match.name, lat: r.match.lat, lon: r.match.lon });
      } else {
        setOriginAsked(r.match
          ? `There's more than one "${name}" - which one?`
          : `I couldn't find "${name}" - try a nearby landmark.`);
      }
    } catch {
      setOriginAsked("Pick your starting point.");
    }
  }

  async function read(q: string) {
    if (!q.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await extractDraft(q);
      setExtraction(result);
      await applyDraft(result.draft, q);
    } catch (e) {
      setExtraction(null);
      setError(
        e instanceof PlanError
          ? e.code === "LLM_UNAVAILABLE"
            ? "The language model isn't running, so I can't read that. You can still use the planner form."
            : e.code === "LLM_TIMEOUT"
              ? "The model took too long. Try a shorter sentence, or use the planner form."
              : e.code === "EXTRACTION_FAILED"
                ? "I couldn't make sense of that. Try naming a place and a few things to do."
                : e.message
          : "Something went wrong reading that.",
      );
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (initialQuery) void read(initialQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function planIt() {
    if (!origin || interests.length === 0) return;
    setPendingPlan(specFromProfile(profile, {
      origin, date, start_time_local: start, end_time_local: end,
      interests,
      budget_inr: budget.trim() ? Number(budget) : null,
      party_size: party,
      constraints: { max_walking_km: 2, meal_required: true, vegetarian },
    }), true);
    // A changing id makes the address different every time, so the planner
    // page always remounts and picks up the request handed to it.
    navigate(`/plan?from=ai-${Date.now()}`);
  }

  const ready = Boolean(origin) && interests.length > 0;

  return (
    <div className="discover">
      <section className="discover-head">
        <span className="eyebrow"><Sparkles size={14} aria-hidden="true" /> Plan with AI</span>
        <h1>Describe your trip in your own words</h1>
        <p className="muted">
          A model reads your sentence and fills in the form below. Everything it
          proposes is yours to correct before anything is planned — it suggests,
          it never decides.
        </p>

        <form className="ask-box" onSubmit={(e) => { e.preventDefault(); void read(text); }}>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            placeholder="e.g. A historic place and a good lunch near Basavanagudi this afternoon, under ₹1000"
            aria-label="Describe your trip"
            disabled={busy}
          />
          <button type="submit" className="primary" disabled={busy || !text.trim()}>
            {busy
              ? <><Loader2 className="spin" size={18} /> Reading your request…</>
              : <><Sparkles size={18} /> Read this</>}
          </button>
        </form>

        {busy && <p className="muted">The model runs on this machine, so this takes a few seconds.</p>}

        {!extraction && !busy && (
          <div className="chips">
            {SUGGESTIONS.map((s) => (
              <button key={s} type="button" className="chip"
                      onClick={() => { setText(s); void read(s); }}>{s}</button>
            ))}
          </div>
        )}

        {error && (
          <div className="error-box" role="alert">
            <AlertTriangle size={20} aria-hidden="true" />
            <div><p>{error}</p></div>
          </div>
        )}
      </section>

      {extraction && (
        <section className="card understood step-enter">
          <h2>Here's what I understood</h2>
          <p className="muted">
            Read by {extraction.model} in {(extraction.latency_ms / 1000).toFixed(1)}s.
            Correct anything below — nothing is planned until you say so.
          </p>

          {originAsked && !origin && (
            <p className="warn"><AlertTriangle size={14} aria-hidden="true" /> {originAsked}</p>
          )}
          <PlaceSearch
            value={origin}
            onChange={(p) => { setOrigin(p); if (p) setOriginAsked(null); }}
            initialText={extraction.draft.origin?.name ?? ""}
          />
          <div className="row">
            <div className="field">
              <label htmlFor="d-date"><CalendarDays size={13} aria-hidden="true" /> Date</label>
              <input id="d-date" type="date" value={date} min={localDate()}
                     onChange={(e) => setDate(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="d-start"><Clock size={13} aria-hidden="true" /> From</label>
              <input id="d-start" type="time" value={start} onChange={(e) => setStart(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="d-end">Until</label>
              <input id="d-end" type="time" value={end} onChange={(e) => setEnd(e.target.value)} />
            </div>
          </div>

          {assumptions.length > 0 && (
            <ul className="notices">
              {assumptions.map((a) => (
                <li key={a}><Info size={14} aria-hidden="true" /> {a}</li>
              ))}
            </ul>
          )}
          {questions.map((q) => (
            <p key={q} className="warn">
              <AlertTriangle size={14} aria-hidden="true" /> {q}
            </p>
          ))}
          {guessedInterests && (
            <p className="muted">
              The model didn't pick these out, so I matched them from your
              words — check they're right.
            </p>
          )}
          <InterestPicker categories={categories} value={interests}
                          onChange={(v) => { setInterests(v); setGuessedInterests(false); }} />
          {interests.length === 0 && (
            <p className="warn">
              <AlertTriangle size={14} aria-hidden="true" /> What would you like to do?
            </p>
          )}

          <div className="row">
            <div className="field">
              <label htmlFor="d-budget"><Wallet size={13} aria-hidden="true" /> Budget ₹</label>
              <input id="d-budget" type="number" min={0} step={100} value={budget}
                     placeholder="No limit" onChange={(e) => setBudget(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="d-party">People</label>
              <input id="d-party" type="number" min={1} max={10} value={party}
                     onChange={(e) => setParty(Number(e.target.value))} />
            </div>
          </div>

          <label className="check">
            <input type="checkbox" checked={vegetarian}
                   onChange={(e) => setVegetarian(e.target.checked)} />
            Vegetarian food only
          </label>

          {extraction.draft.free_text_interests?.length ? (
            <p className="muted">
              I couldn't match: {extraction.draft.free_text_interests.join(", ")} —
              pick the closest categories above.
            </p>
          ) : null}

          {!ready && (
            <p className="field-error">
              <AlertTriangle size={14} aria-hidden="true" />{" "}
              {!origin && interests.length === 0
                ? "Pick a starting point and at least one thing to do, then you can plan."
                : !origin
                  ? "Pick a starting point above, then you can plan."
                  : "Choose at least one thing to do above, then you can plan."}
            </p>
          )}
          <div className="understood-actions">
            <button type="button" className="primary" disabled={!ready} onClick={planIt}>
              Plan this <ArrowRight size={17} />
            </button>
          </div>
        </section>
      )}
    </div>
  );
}