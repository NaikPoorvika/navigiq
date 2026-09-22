import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Check, Eye, EyeOff, Leaf, UtensilsCrossed } from "lucide-react";
import { getCategories } from "../api/client";
import PlaceSearch from "../components/PlaceSearch";
import PreferenceCards from "../components/PreferenceCards";
import PreviewBadge from "../components/PreviewBadge";
import { categoryLabel } from "../lib/categories";
import { href, navigate } from "../lib/router";
import { saveProfile } from "../store/account";
import type { Category, Place } from "../types";
import AuthLayout from "./AuthLayout";

const STEPS = ["Account", "About you", "Preferences"];

export default function OnboardingPage() {
  const [step, setStep] = useState(0);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [name, setName] = useState("");
  const [home, setHome] = useState<Place | null>(null);
  const [interests, setInterests] = useState<string[]>([]);
  const [vegetarian, setVegetarian] = useState<boolean | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [done, setDone] = useState(false);

  useEffect(() => {
    getCategories().then((r) => setCategories(r.categories)).catch(() => setCategories([]));
  }, []);

  const checks = [
    { ok: password.length >= 8, label: "At least 8 characters" },
    { ok: /[A-Za-z]/.test(password), label: "One letter" },
    { ok: /\d/.test(password), label: "One number" },
  ];
  const strength = checks.filter((c) => c.ok).length;

  function next() {
    const e: Record<string, string> = {};
    if (step === 0) {
      if (!/^\S+@\S+\.\S+$/.test(email)) e["email"] = "Enter a valid email address.";
      if (strength < 3) e["password"] = "Password doesn't meet the rules yet.";
      if (confirm !== password) e["confirm"] = "Passwords don't match.";
    }
    if (step === 1) {
      if (!name.trim()) e["name"] = "Tell us what to call you.";
      if (!home) e["home"] = "Pick your neighbourhood from the list.";
    }
    if (step === 2) {
      if (interests.length === 0) e["interests"] = "Choose at least one.";
      if (vegetarian === null) e["food"] = "Choose one.";
    }
    setErrors(e);
    if (Object.keys(e).length > 0) return;

    if (step < 2) {
      setStep(step + 1);
      return;
    }
    saveProfile({ name: name.trim(), email: email.trim(), home, interests, vegetarian: vegetarian ?? false });
    setDone(true);
  }

  if (done) {
    return (
      <AuthLayout>
        <div className="done step-enter">
          <span className="done-check"><Check size={30} aria-hidden="true" /></span>
          <h1>You're all set, {name.split(" ")[0]}.</h1>
          <p className="muted">NavigIQ will plan from {home?.name} around what you like.</p>
          <dl className="summary">
            <dt>Name</dt><dd>{name}</dd>
            <dt>Your interests</dt><dd>{interests.map(categoryLabel).join(" · ")}</dd>
            <dt>Food</dt><dd>{vegetarian ? "Vegetarian" : "Anything"}</dd>
            <dt>Neighbourhood</dt><dd>{home?.name}</dd>
          </dl>
          <button type="button" className="primary inline" onClick={() => navigate("/")}>
            Start exploring <ArrowRight size={17} />
          </button>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <div className="onboarding">
        <ol className="steps">
          {STEPS.map((s, i) => (
            <li key={s} className={i < step ? "done" : i === step ? "active" : ""}>
              <span className="step-dot">{i < step ? <Check size={13} /> : i + 1}</span> {s}
            </li>
          ))}
        </ol>

        {step === 0 && (
          <div className="step-enter">
            <h1>Let's get you started.</h1>
            <p className="muted">
              Create your NavigIQ account.{" "}
              <PreviewBadge reason="Accounts are saved in this browser until sign-up is connected to the backend." />
            </p>
            <div className="field">
              <label htmlFor="email">Email address</label>
              <input id="email" type="email" value={email} autoComplete="email" onChange={(e) => setEmail(e.target.value)} />
              {errors["email"] && <span className="field-error">{errors["email"]}</span>}
            </div>
            <div className="field">
              <label htmlFor="pw">Password</label>
              <div className="input-icon trail-only">
                <input id="pw" type={showPw ? "text" : "password"} value={password}
                       autoComplete="new-password" onChange={(e) => setPassword(e.target.value)} />
                <button type="button" className="eye" onClick={() => setShowPw(!showPw)} aria-label={showPw ? "Hide password" : "Show password"}>
                  {showPw ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </div>
              <div className="strength" data-level={strength}><span /><span /><span /></div>
              <ul className="pw-checks">
                {checks.map((c) => <li key={c.label} className={c.ok ? "ok" : ""}><Check size={13} /> {c.label}</li>)}
              </ul>
              {errors["password"] && <span className="field-error">{errors["password"]}</span>}
            </div>
            <div className="field">
              <label htmlFor="confirm">Confirm password</label>
              <input id="confirm" type={showPw ? "text" : "password"} value={confirm}
                     autoComplete="new-password" onChange={(e) => setConfirm(e.target.value)} />
              {errors["confirm"] && <span className="field-error">{errors["confirm"]}</span>}
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="step-enter">
            <h1>Tell us a little about yourself</h1>
            <p className="muted">Your neighbourhood becomes the default start for every plan.</p>
            <div className="field">
              <label htmlFor="name">Your name</label>
              <input id="name" value={name} autoComplete="name" onChange={(e) => setName(e.target.value)} />
              {errors["name"] && <span className="field-error">{errors["name"]}</span>}
            </div>
            <PlaceSearch value={home} onChange={setHome} error={errors["home"]} />
          </div>
        )}

        {step === 2 && (
          <div className="step-enter">
            <h1>What are you into?</h1>
            <p className="muted">Choose everything that sounds like you.</p>
            <PreferenceCards categories={categories} value={interests} onChange={setInterests} />
            {errors["interests"] && <span className="field-error">{errors["interests"]}</span>}

            <p className="label">Food preference</p>
            <div className="food-choice">
              <button type="button" className={`food-card ${vegetarian === true ? "on" : ""}`} onClick={() => setVegetarian(true)}>
                <Leaf size={20} aria-hidden="true" /><span><strong>Vegetarian</strong><span className="muted">Veg-only spots first</span></span>
              </button>
              <button type="button" className={`food-card ${vegetarian === false ? "on" : ""}`} onClick={() => setVegetarian(false)}>
                <UtensilsCrossed size={20} aria-hidden="true" /><span><strong>Anything</strong><span className="muted">Everything on the menu</span></span>
              </button>
            </div>
            {errors["food"] && <span className="field-error">{errors["food"]}</span>}
          </div>
        )}

        <div className="step-nav">
          {step > 0
            ? <button type="button" className="link" onClick={() => setStep(step - 1)}><ArrowLeft size={15} /> Back</button>
            : <a className="link" href={href("/signin")}>I already have an account</a>}
          <button type="button" className="primary inline" onClick={next}>
            {step === 0 ? "Create account" : step === 2 ? "Finish" : "Continue"} <ArrowRight size={17} />
          </button>
        </div>
      </div>
    </AuthLayout>
  );
}
