import { useEffect, useRef, useState } from "react";
import { Check, Crosshair, Loader2, MapPin } from "lucide-react";
import { nearestPlace, resolvePlace } from "../api/client";
import type { Place, PlaceMatch } from "../types";

interface Props {
  value: Place | null;
  onChange: (place: Place | null) => void;
  error?: string;
  /** Text to start with - e.g. the name the model proposed but we couldn't
   *  resolve. Shown so the user can correct it, not retype it. */
  initialText?: string;
}

type Status = "idle" | "searching" | "ambiguous" | "none" | "error";

/**
 * Origin search through the gazetteer (/places/resolve). The user always picks
 * a real place with real coordinates; an ambiguous name asks instead of guessing.
 */
export default function PlaceSearch({ value, onChange, error, initialText }: Props) {
  const [text, setText] = useState(value?.name ?? initialText ?? "");
  const [options, setOptions] = useState<PlaceMatch[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const latest = useRef(0);
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState<string | null>(null);

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

    /**
   * Ask the browser where we are. Only ever on this button - never on load -
   * and the position is used for this trip, not stored. The browser asks
   * permission itself the first time.
   */
  function useMyLocation() {
    if (!navigator.geolocation) {
      setLocateError("This browser can't share a location.");
      return;
    }
    setLocating(true);
    setLocateError(null);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const { latitude, longitude } = pos.coords;
        try {
          const r = await nearestPlace(latitude, longitude);
          if (!r.in_region) {
            setLocateError("You're outside the Bengaluru area — type a starting point instead.");
          } else {
            // Keep the real position; the place name is only a label.
            const label = r.place ? `Near ${r.place.name}` : "Your location";
            onChange({ name: label, lat: latitude, lon: longitude });
            setText(label);
            setOptions([]);
            setStatus("idle");
          }
        } catch {
          onChange({ name: "Your location", lat: latitude, lon: longitude });
          setText("Your location");
        } finally {
          setLocating(false);
        }
      },
      (err) => {
        setLocating(false);
        setLocateError(err.code === err.PERMISSION_DENIED
          ? "Location permission was declined — type a starting point instead."
          : "Couldn't get your location — type a starting point instead.");
      },
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
    );
  }

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
      <button type="button" className="locate" onClick={useMyLocation} disabled={locating}>
        {locating
          ? <><Loader2 className="spin" size={14} aria-hidden="true" /> Finding you…</>
          : <><Crosshair size={14} aria-hidden="true" /> Use my location</>}
      </button>
      {locateError && <span className="field-error">{locateError}</span>}
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
