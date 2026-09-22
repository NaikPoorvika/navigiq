/**
 * Sign in / create account. Anonymous use stays first-class: this screen
 * explains what an account adds (saved places, preferences, plans across
 * devices) and what already works without one.
 */
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowLeft, Bookmark, Check, Eye, EyeOff, Sparkles, Smartphone } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Logo } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { useDocumentTitle } from "@/lib/hooks";
import { MOOD_ART } from "@/lib/media";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function passwordProblem(p: string): string | null {
  if (p.length < 8) return "At least 8 characters.";
  if (!/[A-Za-z]/.test(p) || !/\d/.test(p)) return "Use at least one letter and one number.";
  return null;
}

function Aside() {
  return (
    <aside className="relative hidden overflow-hidden lg:block">
      <img src={MOOD_ART.canopyPath.src} alt={MOOD_ART.canopyPath.alt} className="absolute inset-0 size-full object-cover" />
      <div className="absolute inset-0 bg-gradient-to-t from-olive-950/90 via-olive-950/55 to-olive-950/30" aria-hidden="true" />
      <div className="relative flex h-full flex-col justify-end p-10 text-white">
        <h2 className="font-display text-3xl font-semibold leading-tight">Bengaluru, figured out</h2>
        <ul className="mt-6 space-y-3 text-white/85">
          {[
            { icon: Bookmark, text: "Keep the places you like, and let them shape what you're shown" },
            { icon: Smartphone, text: "Your plans on every device, with every version kept" },
            { icon: Sparkles, text: "Preferences the planner actually uses — pace, budget, diet" },
          ].map(({ icon: Icon, text }) => (
            <li key={text} className="flex items-start gap-3">
              <Icon className="mt-0.5 size-5 shrink-0 text-sand-300" aria-hidden="true" />
              {text}
            </li>
          ))}
        </ul>
        <p className="mt-8 text-sm text-white/60">Exploring, asking and planning all work without an account.</p>
        <span className="absolute bottom-3 right-4 text-[10px] uppercase tracking-wider text-white/40">Illustration</span>
      </div>
    </aside>
  );
}

function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,28rem)]">
      <main id="main" className="flex flex-col px-5 py-8 sm:px-10">
        <div className="flex items-center justify-between">
          <Logo />
          <Link to="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-4" aria-hidden="true" /> Back to NavigIQ
          </Link>
        </div>
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-10">{children}</div>
      </main>
      <Aside />
    </div>
  );
}

function PasswordField({ id, label, value, onChange, error, hint, autoComplete }: {
  id: string; label: string; value: string; onChange: (v: string) => void; error?: string | null; hint?: string; autoComplete: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <Field id={id} label={label} error={error} hint={hint}>
      <div className="relative">
        <Input
          id={id}
          type={show ? "text" : "password"}
          value={value}
          autoComplete={autoComplete}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
          onChange={(e) => onChange(e.target.value)}
          className="pr-12"
        />
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          aria-label={show ? "Hide password" : "Show password"}
          className="absolute right-2 top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-full text-muted-foreground hover:bg-surface"
        >
          {show ? <EyeOff className="size-4" aria-hidden="true" /> : <Eye className="size-4" aria-hidden="true" />}
        </button>
      </div>
    </Field>
  );
}

function useAfterAuth() {
  const { redirect } = useSearch({ strict: false }) as { redirect?: string };
  const navigate = useNavigate();
  return () => void navigate({ to: redirect && redirect.startsWith("/") ? redirect : "/", replace: true });
}

function friendlyError(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "INVALID_CREDENTIALS": return "That email and password don't match an account.";
      case "EMAIL_TAKEN": return "There's already an account with this email. Try signing in.";
      case "RATE_LIMITED": return "Too many attempts. Wait a minute and try again.";
      case "NETWORK": return "Can't reach NavigIQ. Check your connection.";
      default: return err.message || "That didn't work. Try again.";
    }
  }
  return "That didn't work. Try again.";
}

export function SignInPage() {
  useDocumentTitle("Sign in");
  const { signIn, isAuthenticated } = useAuth();
  const done = useAfterAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string; form?: string }>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (isAuthenticated) done(); }, [isAuthenticated, done]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const next: typeof errors = {};
    if (!EMAIL_RE.test(email.trim())) next.email = "Enter a valid email address.";
    if (!password) next.password = "Enter your password.";
    setErrors(next);
    if (Object.keys(next).length) return;
    setBusy(true);
    try {
      await signIn(email.trim().toLowerCase(), password);
      done();
    } catch (err) {
      setErrors({ form: friendlyError(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell>
      <h1 className="font-display text-3xl font-semibold tracking-tight">Welcome back</h1>
      <p className="mt-2 text-muted-foreground">Sign in to pick up your plans and saved places.</p>
      <form className="mt-8 space-y-5" noValidate onSubmit={submit}>
        <Field id="email" label="Email" error={errors.email}>
          <Input id="email" type="email" value={email} autoComplete="email" inputMode="email"
            aria-invalid={Boolean(errors.email)} aria-describedby={errors.email ? "email-error" : undefined}
            onChange={(e) => { setEmail(e.target.value); setErrors((s) => ({ ...s, email: undefined })); }} />
        </Field>
        <PasswordField id="password" label="Password" value={password} autoComplete="current-password"
          error={errors.password} onChange={(v) => { setPassword(v); setErrors((s) => ({ ...s, password: undefined })); }} />
        {errors.form && <p role="alert" className="rounded-xl bg-danger-soft px-3.5 py-2.5 text-sm text-danger">{errors.form}</p>}
        <Button type="submit" className="w-full" size="lg" loading={busy}>Sign in</Button>
      </form>
      <p className="mt-6 text-sm text-muted-foreground">
        New here? <Link to="/signup" className="font-semibold text-primary hover:underline">Create an account</Link>
      </p>
    </AuthShell>
  );
}

export function SignUpPage() {
  useDocumentTitle("Create account");
  const { signUp, isAuthenticated } = useAuth();
  const done = useAfterAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string; form?: string }>({});
  const [busy, setBusy] = useState(false);
  const strength = passwordProblem(password);

  useEffect(() => { if (isAuthenticated) done(); }, [isAuthenticated, done]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const next: typeof errors = {};
    if (!EMAIL_RE.test(email.trim())) next.email = "Enter a valid email address.";
    const p = passwordProblem(password);
    if (p) next.password = p;
    setErrors(next);
    if (Object.keys(next).length) return;
    setBusy(true);
    try {
      await signUp(email.trim().toLowerCase(), password, name.trim() || undefined);
      done();
    } catch (err) {
      setErrors({ form: friendlyError(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell>
      <h1 className="font-display text-3xl font-semibold tracking-tight">Create your account</h1>
      <p className="mt-2 text-muted-foreground">
        Plans you've already made in this browser come with you.
      </p>
      <form className="mt-8 space-y-5" noValidate onSubmit={submit}>
        <Field id="name" label="Name" hint="Optional — used to greet you.">
          <Input id="name" value={name} autoComplete="name" maxLength={80} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field id="email" label="Email" error={errors.email}>
          <Input id="email" type="email" value={email} autoComplete="email" inputMode="email"
            aria-invalid={Boolean(errors.email)} aria-describedby={errors.email ? "email-error" : undefined}
            onChange={(e) => { setEmail(e.target.value); setErrors((s) => ({ ...s, email: undefined })); }} />
        </Field>
        <PasswordField id="password" label="Password" value={password} autoComplete="new-password"
          error={errors.password} hint="At least 8 characters, with a letter and a number."
          onChange={(v) => { setPassword(v); setErrors((s) => ({ ...s, password: undefined })); }} />
        {password.length > 0 && (
          <p className={cn("-mt-3 flex items-center gap-1.5 text-sm", strength ? "text-muted-foreground" : "text-success")}>
            {!strength && <Check className="size-4" aria-hidden="true" />}
            {strength ?? "Strong enough"}
          </p>
        )}
        {errors.form && <p role="alert" className="rounded-xl bg-danger-soft px-3.5 py-2.5 text-sm text-danger">{errors.form}</p>}
        <Button type="submit" className="w-full" size="lg" loading={busy}>Create account</Button>
      </form>
      <p className="mt-6 text-sm text-muted-foreground">
        Already have one? <Link to="/signin" className="font-semibold text-primary hover:underline">Sign in</Link>
      </p>
    </AuthShell>
  );
}
