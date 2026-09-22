import { ArrowLeft, CalendarDays, Compass, RotateCcw, Trash2 } from "lucide-react";
import ResultView from "../components/ResultView";
import { href, navigate } from "../lib/router";
import { formatDate } from "../lib/time";
import { setPendingPlan } from "../store/pending";
import { deletePlan, getPlan, useSavedPlans } from "../store/plans";

export function PlansPage() {
  const plans = useSavedPlans();
  return (
    <div className="page-narrow">
      <div className="section-head">
        <div>
          <h1>Your plans</h1>
          <p>Saved in this browser. Syncing across devices comes with accounts.</p>
        </div>
      </div>
      {plans.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon"><Compass size={28} aria-hidden="true" /></div>
          <h3>No plans yet</h3>
          <p><a href={href("/plan")}>Plan a trip</a> and it will be saved here.</p>
        </div>
      ) : (
        <div className="plan-grid">
          {plans.map((p) => (
            <a key={p.id} className="plan-card" href={href(`/plans/${p.id}`)}>
              <span className="plan-date"><CalendarDays size={14} aria-hidden="true" /> {formatDate(p.spec.date)}</span>
              <strong>From {p.spec.origin.name ?? "your start"}</strong>
              <span className="plan-stops">{p.data.itinerary.stops.map((s) => s.name).join(" → ")}</span>
              <span className="muted">{p.data.itinerary.stops.length} stops · {p.spec.start_time_local}–{p.spec.end_time_local}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export function SavedPlanPage({ id }: { id: string }) {
  const plan = getPlan(id);
  if (!plan) {
    return (
      <div className="page-narrow">
        <a className="link" href={href("/plans")}><ArrowLeft size={15} /> Your plans</a>
        <div className="empty-state"><h3>This plan isn't here</h3><p>It may have been removed.</p></div>
      </div>
    );
  }
  return (
    <div className="page-narrow">
      <div className="saved-bar">
        <a className="link" href={href("/plans")}><ArrowLeft size={15} /> Your plans</a>
        <div className="saved-actions">
          <button type="button" className="btn-outline" onClick={() => { setPendingPlan(plan.spec, true); navigate("/plan"); }}>
            <RotateCcw size={15} /> Plan again
          </button>
          <button type="button" className="btn-outline danger" onClick={() => { deletePlan(plan.id); navigate("/plans"); }}>
            <Trash2 size={15} /> Delete
          </button>
        </div>
      </div>
      <section className="card"><ResultView data={plan.data} spec={plan.spec} /></section>
    </div>
  );
}
