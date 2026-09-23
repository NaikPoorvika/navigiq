import { useEffect, useState } from "react";
import { ArrowLeft, CalendarDays, Cloud, Compass, Loader2, RotateCcw, Trash2 } from "lucide-react";
import { deleteItinerary, getItinerary, PlanError } from "../api/client";
import ResultView from "../components/ResultView";
import { useRecentPlans } from "../lib/plan-cards";
import { href, navigate } from "../lib/router";
import { useAccount } from "../store/account";
import { setPendingPlan } from "../store/pending";
import { deletePlan, getPlan } from "../store/plans";
import type { SavedPlan } from "../types";

export function PlansPage() {
  const { cards, loading, onServer } = useRecentPlans();
  const { signedIn } = useAccount();

  return (
    <div className="page-narrow">
      <div className="section-head">
        <div>
          <h1>Your plans</h1>
          <p>
            {onServer
              ? "Saved to your account — they follow you to any device."
              : "Saved in this browser. Sign in and new plans follow your account."}
          </p>
        </div>
      </div>

      {loading && <div className="empty-state"><Loader2 className="spin" size={28} aria-hidden="true" /></div>}

      {!loading && cards.length === 0 && (
        <div className="empty-state">
          <div className="empty-icon"><Compass size={28} aria-hidden="true" /></div>
          <h3>No plans yet</h3>
          <p>
            <a href={href("/plan")}>Plan a trip</a>
            {signedIn ? " and it will be saved to your account." : " and it will be saved here."}
          </p>
        </div>
      )}

      {!loading && cards.length > 0 && (
        <div className="plan-grid">
          {cards.map((c) => (
            <a key={c.id} className="plan-card" href={href(`/plans/${c.id}`)}>
              <span className="plan-date"><CalendarDays size={14} aria-hidden="true" /> {c.dateLabel}</span>
              <strong>From {c.originName}</strong>
              <span className="plan-stops">{c.stops}</span>
              <span className="muted">{c.stopCount} stops · {c.timeRange}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export function SavedPlanPage({ id }: { id: string }) {
  const isLocal = id.startsWith("local-");
  const local = isLocal ? getPlan(id.slice("local-".length)) : undefined;
  const [remote, setRemote] = useState<SavedPlan | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isLocal) return;
    getItinerary(Number(id))
      .then(setRemote)
      .catch((e) => setError(e instanceof PlanError && e.code === "NETWORK"
        ? "Can't reach NavigIQ right now."
        : "This plan isn't here — it may have been deleted."));
  }, [id, isLocal]);

  async function remove() {
    if (isLocal && local) deletePlan(local.id);
    else await deleteItinerary(Number(id));
    navigate("/plans");
  }

  const data = isLocal ? local?.data : remote;
  const spec = isLocal ? local?.spec : remote?.spec;

  if (error || (isLocal && !local)) {
    return (
      <div className="page-narrow">
        <a className="link" href={href("/plans")}><ArrowLeft size={15} /> Your plans</a>
        <div className="empty-state">
          <h3>This plan isn't here</h3>
          <p>{error ?? "It may have been removed."}</p>
        </div>
      </div>
    );
  }

  if (!data || !spec) {
    return <div className="page-narrow empty-state"><Loader2 className="spin" size={28} aria-hidden="true" /></div>;
  }

  return (
    <div className="page-narrow">
      <div className="saved-bar">
        <a className="link" href={href("/plans")}><ArrowLeft size={15} /> Your plans</a>
        <div className="saved-actions">
          <button type="button" className="btn-outline"
                  onClick={() => { setPendingPlan(spec, true); navigate("/plan"); }}>
            <RotateCcw size={15} /> Plan again
          </button>
          <button type="button" className="btn-outline danger" onClick={() => void remove()}>
            <Trash2 size={15} /> Delete
          </button>
        </div>
      </div>

      {/* A saved plan has no road shapes stored, so its map draws straight
          lines - the caption under the map says so. */}
      <section className="card"><ResultView data={data} spec={spec} /></section>

      {!data.weather.available && (
        <p className="muted"><Cloud size={13} aria-hidden="true" /> Weather isn't shown for saved plans.</p>
      )}
    </div>
  );
}