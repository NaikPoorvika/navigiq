import { useEffect, useState } from "react";
import {
  Bike, Car, CarFront, CarTaxiFront, Coffee, Footprints, Gauge, Loader2,
  MapPin, Route, Sparkles, Zap, type LucideIcon,
} from "lucide-react";
import { getCategories } from "../api/client";
import type {
  Category, Interest, Place, PlanningMode, TransportMode, TripSpec,
} from "../types";
import InterestPicker from "./InterestPicker";
import PlaceSearch from "./PlaceSearch";
import { localDate, toMinutes } from "../lib/time";

const TRANSPORT: { id: TransportMode; label: string; icon: LucideIcon }[] = [
  { id: "walking", label: "Walking", icon: Footprints },
  { id: "auto", label: "Auto", icon: CarTaxiFront },
  { id: "cab", label: "Cab", icon: Car },
  { id: "own_car", label: "Own car", icon: CarFront },
  { id: "bike", label: "Bike", icon: Bike },
];

const MODES: { id: PlanningMode; label: string; icon: LucideIcon }[] = [
  { id: "quick", label: "Quick", icon: Zap },
  { id: "balanced", label: "Balanced", icon: Gauge },
  { id: "relaxed", label: "Relaxed", icon: Coffee },
];

interface Props {
  onSubmit: (spec: TripSpec) => void;
  busy: boolean;
  initial: Partial<TripSpec> | null;
}

export default function PlanForm({ onSubmit, busy, initial }: Props) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryError, setCategoryError] = useState(false);

  const [origin, setOrigin] = useState<Place | null>(initial?.origin ?? null);
  const [date, setDate] = useState(initial?.date ?? localDate());
  const [start, setStart] = useState(initial?.start_time_local ?? "15:00");
  const [end, setEnd] = useState(initial?.end_time_local ?? "20:00");
  const [budget, setBudget] = useState(
    initial?.budget_inr != null ? String(initial.budget_inr) : "",
  );
  const [party, setParty] = useState(initial?.party_size ?? 1);
  const [maxWalk, setMaxWalk] = useState(initial?.constraints?.max_walking_km ?? 2);
  const [vegetarian, setVegetarian] = useState(initial?.constraints?.vegetarian ?? false);
  const [interests, setInterests] = useState<Interest[]>(initial?.interests ?? []);
  const [transport, setTransport] = useState<TransportMode[]>(
    initial?.transport ?? ["walking", "auto"],
  );
  const [mode, setMode] = useState<PlanningMode>(initial?.mode ?? "balanced");
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    getCategories()
      .then((r) => setCategories(r.categories))
      .catch(() => setCategoryError(true));
  }, []);

  function toggleTransport(id: TransportMode) {
    setTransport((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id],
    );
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const found: Record<string, string> = {};
    if (!origin) found["origin"] = "Pick a starting place from the list.";
    if (interests.length === 0) found["interests"] = "Choose at least one thing to do.";
    if (transport.length === 0) found["transport"] = "Choose at least one way to get around.";
    if (toMinutes(end) - toMinutes(start) < 60) {
      found["time"] = "Finish at least an hour after you start.";
    }
    setErrors(found);
    if (Object.keys(found).length > 0 || !origin) return;

    onSubmit({
      origin,
      date,
      start_time_local: start,
      end_time_local: end,
      budget_inr: budget.trim() ? Number(budget) : null,
      party_size: party,
      interests,
      transport,
      constraints: { max_walking_km: maxWalk, meal_required: true, vegetarian },
      mode,
    });
  }

  return (
    <form id="plan-form" onSubmit={submit} noValidate>
      <div className="form-section">
        <div className="section-title"><MapPin size={17} aria-hidden="true" /> Where and when</div>
        <PlaceSearch value={origin} onChange={setOrigin} error={errors["origin"]} />
        <div className="row">
          <div className="field">
            <label htmlFor="date">Date</label>
            <input id="date" type="date" value={date} min={localDate()}
                   onChange={(e) => setDate(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="start">From</label>
            <input id="start" type="time" value={start}
                   onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="end">Until</label>
            <input id="end" type="time" value={end}
                   onChange={(e) => setEnd(e.target.value)} />
          </div>
        </div>
        {errors["time"] && <span className="field-error">{errors["time"]}</span>}
      </div>

      <div className="form-section">
        <div className="section-title"><Sparkles size={17} aria-hidden="true" /> What you'd like to do</div>
        {categoryError ? (
          <p className="field-error">Couldn't load categories — is the backend running?</p>
        ) : (
          <InterestPicker categories={categories} value={interests}
                          onChange={setInterests} error={errors["interests"]} />
        )}
        <label className="check">
          <input type="checkbox" checked={vegetarian}
                 onChange={(e) => setVegetarian(e.target.checked)} />
          Vegetarian food only
        </label>
      </div>

      <div className="form-section">
        <div className="section-title"><Route size={17} aria-hidden="true" /> How you'll get around</div>
        <div className="field">
          <div className="chips">
            {TRANSPORT.map(({ id, label, icon: Icon }) => (
              <button key={id} type="button"
                      className={`chip ${transport.includes(id) ? "on" : ""}`}
                      aria-pressed={transport.includes(id)}
                      onClick={() => toggleTransport(id)}>
                <Icon size={15} aria-hidden="true" /> {label}
              </button>
            ))}
          </div>
          {errors["transport"] && <span className="field-error">{errors["transport"]}</span>}
        </div>

        <div className="field">
          <label>Pace</label>
          <div className="chips">
            {MODES.map(({ id, label, icon: Icon }) => (
              <button key={id} type="button"
                      className={`chip ${mode === id ? "on" : ""}`}
                      aria-pressed={mode === id}
                      onClick={() => setMode(id)}>
                <Icon size={15} aria-hidden="true" /> {label}
              </button>
            ))}
          </div>
        </div>

        <div className="row">
          <div className="field">
            <label htmlFor="budget">Budget ₹</label>
            <input id="budget" type="number" min={0} step={100} value={budget}
                   placeholder="No limit" onChange={(e) => setBudget(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="party">People</label>
            <input id="party" type="number" min={1} max={10} value={party}
                   onChange={(e) => setParty(Number(e.target.value))} />
          </div>
          <div className="field">
            <label htmlFor="walk">Walk (km)</label>
            <input id="walk" type="number" min={0} max={15} step={0.5} value={maxWalk}
                   onChange={(e) => setMaxWalk(Number(e.target.value))} />
          </div>
        </div>
      </div>

      <button type="submit" className="primary" disabled={busy}>
        {busy
          ? <><Loader2 className="spin" size={18} aria-hidden="true" /> Planning…</>
          : <><Sparkles size={18} aria-hidden="true" /> Plan my trip</>}
      </button>
    </form>
  );
}
