import { useState } from "react";
import { ArrowRight } from "lucide-react";
import PreviewBadge from "../components/PreviewBadge";
import { href, navigate } from "../lib/router";
import { signIn } from "../store/account";
import AuthLayout from "./AuthLayout";

export default function SignInPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    if (signIn(email)) navigate("/");
    else setError("No account with that email in this browser. Create one first.");
  }

  return (
    <AuthLayout>
      <form className="onboarding step-enter" onSubmit={submit} noValidate>
        <h1>Welcome back.</h1>
        <p className="muted">
          Sign in to plan from home.{" "}
          <PreviewBadge reason="Accounts are saved in this browser until sign-in is connected to the backend." />
        </p>
        <div className="field">
          <label htmlFor="si-email">Email address</label>
          <input id="si-email" type="email" value={email} autoComplete="email" onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="si-pw">Password</label>
          <input id="si-pw" type="password" value={password} autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} />
        </div>
        {error && <p className="field-error">{error}</p>}
        <button type="submit" className="primary">Sign in <ArrowRight size={17} /></button>
        <p className="muted center">New here? <a href={href("/welcome")}>Create an account</a></p>
      </form>
    </AuthLayout>
  );
}
