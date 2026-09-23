import { useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2, LogOut, Trash2 } from "lucide-react";
import { getCategories, PlanError } from "../api/client";
import PlaceSearch from "../components/PlaceSearch";
import PreferenceCards from "../components/PreferenceCards";
import { href, navigate } from "../lib/router";
import { deleteAccount, saveProfile, signOut, useAccount } from "../store/account";
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
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

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

  async function remove() {
    if (!deletePassword) {
      setDeleteError("Enter your password to confirm.");
      return;
    }
    setDeleting(true);
    setDeleteError("");
    try {
      await deleteAccount(deletePassword);
      navigate("/");
    } catch (err) {
      setDeleteError(
        err instanceof PlanError && err.code === "AUTH"
          ? "That password isn't right."
          : "Couldn't delete the account. Please try again.",
      );
      setDeleting(false);
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

      <section className="card danger-zone">
        <h2 className="card-title">Delete account</h2>
        <p className="muted">
          Permanently removes your account and profile — name, home, interests and food
          preference — from NavigIQ, and the plans saved in this browser. This can't be undone.
        </p>
        {!confirmingDelete ? (
          <button type="button" className="btn-outline danger" onClick={() => setConfirmingDelete(true)}>
            <Trash2 size={15} /> Delete my account
          </button>
        ) : (
          <div className="confirm-delete step-enter">
            <p className="warn"><AlertTriangle size={14} aria-hidden="true" /> Enter your password to confirm.</p>
            <div className="field">
              <label htmlFor="del-pw">Password</label>
              <input id="del-pw" type="password" value={deletePassword} autoComplete="current-password"
                     onChange={(e) => setDeletePassword(e.target.value)} disabled={deleting} />
            </div>
            {deleteError && <p className="field-error" role="alert">{deleteError}</p>}
            <div className="profile-actions">
              <button type="button" className="btn-danger" onClick={() => void remove()} disabled={deleting}>
                {deleting ? <><Loader2 className="spin" size={16} /> Deleting…</> : "Delete permanently"}
              </button>
              <button type="button" className="btn-outline"
                      onClick={() => { setConfirmingDelete(false); setDeletePassword(""); setDeleteError(""); }}
                      disabled={deleting}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
