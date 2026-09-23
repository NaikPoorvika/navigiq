import { AlertTriangle, ArrowRight, PencilLine } from "lucide-react";
import type { PlanError } from "../api/client";
import { relaxOptions } from "../lib/relax";
import type { TripSpec } from "../types";

const REASONS: Record<string, string> = {
  TIME_INFEASIBLE: "There isn't enough time for everything you asked for.",
  BUDGET_INFEASIBLE: "The budget is too low for these places.",
  REACH_INFEASIBLE: "Some of what you asked for isn't available near your starting point.",
  HOURS_INFEASIBLE: "Some places are closed during your time window.",
  WEATHER_INFEASIBLE: "Heavy rain is forecast, and some of your choices are outdoors.",
};

interface Props {
  error: PlanError;
  spec: TripSpec;
  onApply: (spec: TripSpec) => void;
  onEdit: () => void;
}

/** INFEASIBLE is a normal outcome: explain why, and offer concrete fixes. */
export default function FeasibilityBanner({ error, spec, onApply, onEdit }: Props) {
  const details = error.details ?? {};
  const reasons = (details.violated ?? []).map((v) => REASONS[v] ?? v);
  const options = relaxOptions(spec, details.suggested_relaxations ?? []);
  const bounds = details.bounds ?? {};
  const need = bounds["total_required_minutes"];
  const have = bounds["available_minutes"];

  return (
    <div className="banner step-enter" role="alert">
      <div className="banner-head">
        <span className="banner-icon"><AlertTriangle size={20} aria-hidden="true" /></span>
        <div>
          <h3>This trip doesn't quite fit</h3>
          {reasons.map((r) => <p key={r}>{r}</p>)}
          {typeof need === "number" && typeof have === "number" && need > have && (
            <p className="muted">Needs about {need} minutes; you have {have}.</p>
          )}
        </div>
      </div>

      {options.length > 0 && (
        <>
          <p className="label">Try one of these:</p>
          <div className="relax-list">
            {options.map((o) => (
              <button key={o.key} type="button" className="relax" onClick={() => onApply(o.apply(spec))}>
                <span className="relax-text">
                  <strong>{o.label}</strong>
                  <span className="muted">{o.detail}</span>
                  {o.changesWhatYouAsked && <span className="tag">Changes what you asked for</span>}
                </span>
                <ArrowRight size={16} aria-hidden="true" />
              </button>
            ))}
          </div>
        </>
      )}

      <button type="button" className="link" onClick={onEdit}>
        <PencilLine size={15} aria-hidden="true" /> Edit the form instead
      </button>
    </div>
  );
}
