import {
  AlertTriangle, MapPinOff, RefreshCw, ServerCrash, ShieldAlert, WifiOff,
  type LucideIcon,
} from "lucide-react";
import type { PlanError } from "../api/client";

const VIEWS: Record<string, { icon: LucideIcon; title: string; body: string }> = {
  SEMANTIC_INVALID: {
    icon: AlertTriangle,
    title: "Something in the request doesn't add up",
    body: "Check the details below and try again.",
  },
  NO_CANDIDATES: {
    icon: MapPinOff,
    title: "Nothing matched near your starting point",
    body: "Try a different starting point, or choose other things to do.",
  },
  ROUTING_UNAVAILABLE: {
    icon: ServerCrash,
    title: "Travel times are unavailable right now",
    body: "NavigIQ won't guess travel times, so no plan was made. Try again in a minute.",
  },
  VALIDATION_FAILED: {
    icon: ShieldAlert,
    title: "This plan didn't pass our checks",
    body: "Every plan is re-checked before you see it, and this one failed — so it isn't shown. Try again, or change the time window.",
  },
  NETWORK: {
    icon: WifiOff,
    title: "Can't reach NavigIQ",
    body: "The planner isn't responding. Is the backend running?",
  },
};

const FALLBACK = {
  icon: AlertTriangle,
  title: "Something went wrong",
  body: "Please try again.",
};

interface Props {
  error: PlanError;
  onRetry: () => void;
}

/** One screen per backend error code. INFEASIBLE is handled by FeasibilityBanner. */
export default function PlanErrorView({ error, onRetry }: Props) {
  const view = VIEWS[error.code] ?? FALLBACK;
  const Icon = view.icon;
  const fieldErrors = error.details?.errors ?? [];

  return (
    <div className="error-view step-enter" role="alert">
      <span className="error-icon"><Icon size={24} aria-hidden="true" /></span>
      <h3>{view.title}</h3>
      <p>{view.body}</p>
      {fieldErrors.length > 0 && (
        <ul className="field-errors">
          {fieldErrors.map((e) => (
            <li key={`${e.field}-${e.message}`}>
              {e.field && <strong>{e.field.replace(/_/g, " ")}: </strong>}{e.message}
            </li>
          ))}
        </ul>
      )}
      {error.code !== "SEMANTIC_INVALID" && (
        <button type="button" className="btn-outline" onClick={onRetry}>
          <RefreshCw size={15} aria-hidden="true" /> Try again
        </button>
      )}
      <span className="muted">Code: {error.code}</span>
    </div>
  );
}
