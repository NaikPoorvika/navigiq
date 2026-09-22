import { useEffect, useState } from "react";
import { Check, Loader2, LogOut } from "lucide-react";
import { getCategories, PlanError } from "../api/client";
import PlaceSearch from "../components/PlaceSearch";
import PreferenceCards from "../components/PreferenceCards";
import { href, navigate } from "../lib/router";
import { saveProfile, signOut, useAccount } from "../store/account";
import type { Category, Place } from "../types";

export default function ProfilePage() {
  const { profile, signedIn, ready } = useAccount();
  const [name, setName] = useState(profile?.name ?? "");
  const [home, setHome] = useState<Place | null>(profile?.home ?? null);
  const [interests, setInterests] = useState<string[]>(profile?.interests ?? []);
  const [vegetarian, setVegetarian] = useState(profile?.vegetarian ?? false);
  const [categories, setCategories] = useState<Category[]>([]);
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState("");

  useEffect(() => {
    getCategories().then((r) => setCategories(r.categories)).catch(() => setCategories([]));
  }, []);

  // The profile arrives after the saved session is checked - fill the form then.
  useEffect(() => {
    if (!profile) return;
    setName(profile.name);
    setHome(profile.home);
    setInterests(profile.interests);
    setVegetarian(profile.vegetarian);
  }, [profile]);

  if (!ready) return <div className="page-narrow empty-state"><Loader2 className="spin" size={28} /></div>;

  if (!profile || !signedIn) {
    return (
      <div className="page-narrow empty-state">
        <h3>You're not signed in</h3>
        <p><a href={href("/signin")}>Sign in</a> or <a href={href("/welcome")}>create an account</a>.</p>
      </div>
    );
  }

  async function save() {
    setStatus("saving");
    setError("");
    try {
      await saveProfile({ name: name.trim(), home, interests, vegetarian });
      setStatus("saved");
      window.setTimeout(() => setStatus("idle"), 2000);
    } catch (err) {
      setStatus("idle");
      setError(err instanceof PlanError ? err.message : "Couldn't save. Please try again.");
    }
  }

  return (
    <div className="page-narrow">
      <div className="section-head">
        <div>
          <h1>Your profile</h1>
          <p className="muted">{profile.email}</p>
        </div>
      </div>

      <section className="card">
        <div className="field">
          <label htmlFor="pname">Name</label>
          <input id="pname" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <PlaceSearch value={home} onChange={setHome} />
        <label className="check">
          <input type="checkbox" checked={vegetarian} onChange={(e) => setVegetarian(e.target.checked)} />
          Vegetarian food only
        </label>
      </section>

      <section className="card">
        <h2 className="card-title">Interests</h2>
        <PreferenceCards categories={categories} value={interests} onChange={setInterests} />
      </section>

      {error && <p className="field-error" role="alert">{error}</p>}

      <div className="profile-actions">
        <button type="button" className="primary inline" onClick={() => void save()} disabled={status === "saving"}>
          {status === "saving" ? <><Loader2 className="spin" size={17} /> Saving…</>
            : status === "saved" ? <><Check size={17} /> Saved</> : "Save changes"}
        </button>
        <button type="button" className="btn-outline" onClick={() => { signOut(); navigate("/"); }}>
          <LogOut size={15} /> Sign out
        </button>
      </div>
    </div>
  );
}
