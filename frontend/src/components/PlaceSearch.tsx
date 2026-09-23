import { useEffect, useRef, useState } from "react";
import { Check, Loader2, MapPin } from "lucide-react";
import { resolvePlace } from "../api/client";
import type { Place, PlaceMatch } from "../types";

interface Props {
  value: Place | null;
  onChange: (place: Place | null) => void;
  error?: string;
}

type Status = "idle" | "searching" | "ambiguous" | "none" | "error";

/**
 * Origin search through the gazetteer (/places/resolve). The user always picks
 * a real place with real coordinates; an ambiguous name asks instead of guessing.
 */
export default function PlaceSearch({ value, onChange, error }: Props) {
  const [text, setText] = useState(value?.name ?? "");
  const [options, setOptions] = useState<PlaceMatch[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const latest = useRef(0);

  useEffect(() => {
    if (value && text === value.name) return; // just picked: nothing to search

    const q = text.trim();
    if (q.length < 3) {
      setOptions([]);
      setStatus("idle");
      return;
    }

    const id = ++latest.current;
    setStatus("searching");
    const timer = window.setTimeout(async () => {
      try {
        const r = await resolvePlace(q);
        if (id !== latest.current) return; // a newer search has started
        setOptions(r.match ? [r.match, ...r.alternatives] : []);
        setStatus(!r.match ? "none" : r.needs_clarification ? "ambiguous" : "idle");
      } catch {
        if (id === latest.current) setStatus("error");
      }
    }, 350);
    return () => window.clearTimeout(timer);
  }, [text, value]);

  function pick(m: PlaceMatch) {
    onChange({ name: m.name, lat: m.lat, lon: m.lon });
    setText(m.name);
    setOptions([]);
    setStatus("idle");
  }

  return (
    <div className="field">
      <label htmlFor="origin">Starting from</label>
      <div className="input-icon">
        <MapPin size={17} aria-hidden="true" />
        <input
          id="origin"
          value={text}
          placeholder="Koramangala, Cubbon Park, MG Road…"
          autoComplete="off"
          onChange={(e) => {
            setText(e.target.value);
            if (value) onChange(null); // editing clears the chosen place
          }}
        />
        {status === "searching" && <Loader2 className="spin input-trail" size={16} aria-hidden="true" />}
      </div>

      {value && (
        <span className="picked">
          <Check size={13} aria-hidden="true" /> {value.name}
        </span>
      )}
      {status === "ambiguous" && (
        <span className="warn">There's more than one "{text.trim()}" — pick the right one:</span>
      )}
      {status === "none" && (
        <span className="field-error">No place found. Try a nearby landmark or neighbourhood.</span>
      )}
      {status === "error" && (
        <span className="field-error">Can't search places right now.</span>
      )}

      {options.length > 0 && !value && (
        <ul className="place-options" role="listbox">
          {options.map((m, i) => (
            <li key={`${m.name}-${m.lat}-${m.lon}`}>
              <button type="button" onClick={() => pick(m)}>
                <MapPin size={15} aria-hidden="true" />
                <span>
                  <strong>{m.name}</strong>
                  <span className="muted">
                    {" "}{m.kind.replace(/_/g, " ")}
                    {i === 0 && status !== "ambiguous" ? " · best match" : ""}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <span className="field-error">{error}</span>}
    </div>
  );
}
