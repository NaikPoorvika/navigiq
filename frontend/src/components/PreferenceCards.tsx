import { Check, Plus } from "lucide-react";
import { categoryLabel } from "../lib/categories";
import type { Category } from "../types";
import CategoryPhoto from "./CategoryPhoto";

interface Props {
  categories: Category[];
  value: string[];
  onChange: (value: string[]) => void;
}

/** Photo cards built from the real category list - never a category the planner lacks. */
export default function PreferenceCards({ categories, value, onChange }: Props) {
  const toggle = (key: string) =>
    onChange(value.includes(key) ? value.filter((k) => k !== key) : [...value, key]);

  return (
    <div className="pref-grid">
      {categories.filter((c) => c.poi_count > 0).map((c) => {
        const on = value.includes(c.key);
        return (
          <button
            key={c.key}
            type="button"
            className={`pref-card ${on ? "on" : ""}`}
            aria-pressed={on}
            onClick={() => toggle(c.key)}
          >
            <CategoryPhoto category={c.key} variant="tile" showCredit={false} />
            <span className="pref-shade" />
            <span className="pref-text">
              <strong>{c.display_name || categoryLabel(c.key)}</strong>
              <span>{on ? <><Check size={13} aria-hidden="true" /> Selected</> : <><Plus size={13} aria-hidden="true" /> Select</>}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
