import { useEffect, useState } from "react";
import { Check, Circle, Loader2 } from "lucide-react";

const STAGES = [
  "Checking the weather",
  "Finding places that fit",
  "Working out travel times",
  "Choosing the best order",
  "Double-checking hours and timings",
];

/**
 * Staged progress while a plan is built. The backend doesn't stream its
 * stages, so this advances on a timer and holds on the last step until the
 * response arrives - it shows what is happening, not a precise measurement.
 */
export default function PlanProgress() {
  const [stage, setStage] = useState(0);

  useEffect(() => {
    const t = window.setInterval(
      () => setStage((s) => Math.min(s + 1, STAGES.length - 1)),
      1300,
    );
    return () => window.clearInterval(t);
  }, []);

  return (
    <div className="progress step-enter" role="status" aria-live="polite">
      <h3>Planning your trip</h3>
      <ol>
        {STAGES.map((label, i) => (
          <li key={label} className={i < stage ? "done" : i === stage ? "active" : ""}>
            {i < stage
              ? <Check size={16} aria-hidden="true" />
              : i === stage
                ? <Loader2 className="spin" size={16} aria-hidden="true" />
                : <Circle size={16} aria-hidden="true" />}
            {label}
          </li>
        ))}
      </ol>
      <p className="muted">Usually takes a few seconds.</p>
    </div>
  );
}
