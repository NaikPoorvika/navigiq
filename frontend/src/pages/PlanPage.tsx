import { useEffect, useRef, useState } from "react";
import { BadgeCheck, Clock, Map as MapIcon, Route } from "lucide-react";
import { createPlan, PlanError } from "../api/client";
import FeasibilityBanner from "../components/FeasibilityBanner";
import PlanErrorView from "../components/PlanErrorView";
import PlanForm from "../components/PlanForm";
import PlanProgress from "../components/PlanProgress";
import ResultView from "../components/ResultView";
import { specFromProfile } from "../lib/defaults";
import { useAccount } from "../store/account";
import { peekPendingPlan } from "../store/pending";
import { savePlan } from "../store/plans";
import type { PlanResponse, TripSpec } from "../types";
/** The last request planned automatically - module level, so a remount in
 *  development doesn't plan the same request twice. */
let lastPlannedToken: string | null = null;

type Phase =
  | { kind: "empty" }
  | { kind: "loading" }
  | { kind: "result"; data: PlanResponse; spec: TripSpec }
  | { kind: "error"; error: PlanError; spec: TripSpec };

export default function PlanPage() {
  const { profile, signedIn } = useAccount();
  // Read once: a request handed over from Home, a plan idea, or Plan with AI.
  const [pending] = useState(peekPendingPlan);
  const [formSpec, setFormSpec] = useState<Partial<TripSpec> | null>(
    () => pending?.spec ?? specFromProfile(profile),
  );
  const [formKey, setFormKey] = useState(0);
  const [phase, setPhase] = useState<Phase>({ kind: "empty" });
  const resultRef = useRef<HTMLElement>(null);

  async function plan(spec: TripSpec, fromSuggestion = false) {
    setFormSpec(spec);
    if (fromSuggestion) setFormKey((k) => k + 1); // remount so the form shows the change
    setPhase({ kind: "loading" });
    if (window.innerWidth < 960) {
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    try {
      const data = await createPlan(spec);
      // Signed in, the backend already saved it to the account - keeping a
      // browser copy too would show the same trip twice.
      if (!signedIn) savePlan(spec, data);
      setPhase({ kind: "result", data, spec });
    } catch (e) {
      const error = e instanceof PlanError ? e : new PlanError({ code: "UNKNOWN", message: String(e) });
      setPhase({ kind: "error", error, spec });
    }
  }

  useEffect(() => {
    const p = peekPendingPlan();
    if (!p || p.token === lastPlannedToken) return;   // already handled
    lastPlannedToken = p.token;
    if (p.autoPlan && p.spec.origin && p.spec.interests?.length) {
      void plan(p.spec as TripSpec);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <section className="hero compact">
        <h1>Plan a trip</h1>
        <div className="promises">
          <span><MapIcon size={15} aria-hidden="true" /> Real places from OpenStreetMap</span>
          <span><Route size={15} aria-hidden="true" /> Travel times from road data</span>
          <span><Clock size={15} aria-hidden="true" /> Opening hours checked where known</span>
          <span><BadgeCheck size={15} aria-hidden="true" /> Every plan verified before you see it</span>
        </div>
      </section>

      <div className="app-main">
        <section className="card form-card">
          <PlanForm key={formKey} onSubmit={(s) => void plan(s)} busy={phase.kind === "loading"} initial={formSpec} />
        </section>

        <section className="card result-card" ref={resultRef} aria-live="polite">
          {phase.kind === "empty" && (
            <div className="empty-state">
              <div className="empty-icon"><Route size={28} aria-hidden="true" /></div>
              <h3>Your itinerary appears here</h3>
              <p>Pick a starting point and a few things to do, then press <strong>Plan my trip</strong>.</p>
            </div>
          )}
          {phase.kind === "loading" && <PlanProgress />}
          {phase.kind === "result" && (
            <ResultView data={phase.data} spec={phase.spec}
                        onChangeSpec={(s) => void plan(s, true)} />
          )}
          {phase.kind === "error" && phase.error.code === "INFEASIBLE" && (
            <FeasibilityBanner
              error={phase.error}
              spec={phase.spec}
              onApply={(s) => void plan(s, true)}
              onEdit={() => document.getElementById("plan-form")?.scrollIntoView({ behavior: "smooth" })}
            />
          )}
          {phase.kind === "error" && phase.error.code !== "INFEASIBLE" && (
            <PlanErrorView error={phase.error} onRetry={() => void plan(phase.spec)} />
          )}
        </section>
      </div>
    </>
  );
}
