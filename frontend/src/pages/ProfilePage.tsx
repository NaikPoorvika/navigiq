import { useEffect, useState } from "react";
import { Check, LogOut, Trash2 } from "lucide-react";
import { getCategories } from "../api/client";
import PlaceSearch from "../components/PlaceSearch";
import PreferenceCards from "../components/PreferenceCards";
import PreviewBadge from "../components/PreviewBadge";
import { href, navigate } from "../lib/router";
import { deleteAccount, saveProfile, signOut, useAccount } from "../store/account";
import type { Category, Place } from "../types";

export default function ProfilePage() {
  const { profile, signedIn } = useAccount();
  const [name, setName] = useState(profile?.name ?? "");
  const [home, setHome] = useState<Place | null>(profile?.home ?? null);
  const [interests, setInterests] = useState<string[]>(profile?.interests ?? []);
  const [vegetarian, setVegetarian] = useState(profile?.vegetarian ?? false);
  const [categories, setCategories] = useState<Category[]>([]);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getCategories().then((r) => setCategories(r.categories)).catch(() => setCategories([]));
  }, []);

  if (!profile || !signedIn) {
    return (
      <div className="page-narrow empty-state">
        <h3>You're not signed in</h3>
        <p><a href={href("/signin")}>Sign in</a> or <a href={href("/welcome")}>create an account</a>.</p>
      </div>
    );
  }

  function save() {
    if (!profile) return;
    saveProfile({ ...profile, name: name.trim() || profile.name, home, interests, vegetarian });
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="page-narrow">
      <div className="section-head">
        <div>
          <h1>Your profile</h1>
          <p className="muted">{profile.email} <PreviewBadge reason="Saved in this browser until accounts are connected to the backend." /></p>
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

      <div className="profile-actions">
        <button type="button" className="primary inline" onClick={save}>
          {saved ? <><Check size={17} /> Saved</> : "Save changes"}
        </button>
        <button type="button" className="btn-outline" onClick={() => { signOut(); navigate("/"); }}>
          <LogOut size={15} /> Sign out
        </button>
        <button type="button" className="btn-outline danger" onClick={() => { deleteAccount(); navigate("/"); }}>
          <Trash2 size={15} /> Delete account from this browser
        </button>
      </div>
    </div>
  );
}
