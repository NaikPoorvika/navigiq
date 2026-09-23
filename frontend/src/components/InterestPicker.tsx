import type { Category, Interest, Priority } from "../types";
import { categoryIcon } from "../lib/categories";

interface Props {
  categories: Category[];
  value: Interest[];
  onChange: (value: Interest[]) => void;
  error?: string;
}

const PRIORITY: { id: Priority; label: string }[] = [
  { id: "must", label: "Must" },
  { id: "should", label: "Prefer" },
  { id: "nice_to_have", label: "If it fits" },
];

/**
 * Chips built from /pois/categories, so the form can never offer a category
 * the planner doesn't understand.
 */
export default function InterestPicker({ categories, value, onChange, error }: Props) {
  const chosen = new Set(value.map((i) => i.category));

  function toggle(key: string) {
    onChange(
      chosen.has(key)
        ? value.filter((i) => i.category !== key)
        : [...value, { category: key, count: 1, priority: "should" }],
    );
  }

  function update(key: string, patch: Partial<Interest>) {
    onChange(value.map((i) => (i.category === key ? { ...i, ...patch } : i)));
  }

  const available = categories.filter((c) => c.poi_count > 0);

  return (
    <div className="field">
      {available.length === 0 && <span className="muted">Loading categories…</span>}
      <div className="chips">
        {available.map((c) => {
          const Icon = categoryIcon(c.key);
          const on = chosen.has(c.key);
          return (
            <button
              key={c.key}
              type="button"
              className={`chip ${on ? "on" : ""}`}
              aria-pressed={on}
              onClick={() => toggle(c.key)}
            >
              <Icon size={15} aria-hidden="true" /> {c.display_name}
            </button>
          );
        })}
      </div>

      {value.length > 0 && (
        <ul className="interest-rows">
          {value.map((i) => {
            const Icon = categoryIcon(i.category);
            return (
              <li key={i.category}>
                <span className="interest-name">
                  <Icon size={15} aria-hidden="true" />
                  {categories.find((c) => c.key === i.category)?.display_name ?? i.category}
                </span>
                <select
                  aria-label="Priority"
                  value={i.priority}
                  onChange={(e) => update(i.category, { priority: e.target.value as Priority })}
                >
                  {PRIORITY.map((p) => (
                    <option key={p.id} value={p.id}>{p.label}</option>
                  ))}
                </select>
                <select
                  aria-label="How many"
                  value={i.count}
                  onChange={(e) => update(i.category, { count: Number(e.target.value) })}
                >
                  {[1, 2, 3].map((n) => (
                    <option key={n} value={n}>× {n}</option>
                  ))}
                </select>
              </li>
            );
          })}
        </ul>
      )}
      {error && <span className="field-error">{error}</span>}
    </div>
  );
}
