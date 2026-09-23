import { useState } from "react";
import { ArrowRight, Loader2 } from "lucide-react";
import { PlanError } from "../api/client";
import { href, navigate } from "../lib/router";
import { signIn } from "../store/account";
import AuthLayout from "./AuthLayout";

export default function SignInPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await signIn(email.trim(), password);
      navigate("/");
    } catch (err) {
      setError(
        err instanceof PlanError && err.code === "AUTH"
          ? "That email and password don't match an account."
          : err instanceof PlanError && err.code === "NETWORK"
            ? "Can't reach NavigIQ right now. Please try again."
            : "Something went wrong. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout>
      <form className="onboarding step-enter" onSubmit={(e) => void submit(e)} noValidate>
        <h1>Welcome back.</h1>
        <p className="muted">Sign in to plan from home.</p>
        <div className="field">
          <label htmlFor="si-email">Email address</label>
          <input id="si-email" type="email" value={email} autoComplete="email"
                 onChange={(e) => setEmail(e.target.value)} disabled={busy} />
        </div>
        <div className="field">
          <label htmlFor="si-pw">Password</label>
          <input id="si-pw" type="password" value={password} autoComplete="current-password"
                 onChange={(e) => setPassword(e.target.value)} disabled={busy} />
        </div>
        {error && <p className="field-error" role="alert">{error}</p>}
        <button type="submit" className="primary" disabled={busy}>
          {busy ? <><Loader2 className="spin" size={17} /> Signing in…</> : <>Sign in <ArrowRight size={17} /></>}
        </button>
        <p className="muted center">New here? <a href={href("/welcome")}>Create an account</a></p>
      </form>
    </AuthLayout>
  );
}
