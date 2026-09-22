import type { ReactNode } from "react";
import { Compass, Sparkles } from "lucide-react";
import { href } from "../lib/router";

/** Split layout for sign-up and sign-in, as in the prototype. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="auth">
      <aside className="auth-side">
        <a className="brand" href={href("/")}>
          <span className="brand-mark"><Compass size={20} aria-hidden="true" /></span>
          <span className="brand-name spaced">NAVIGIQ</span>
        </a>
        <div className="auth-pitch">
          <h2>Plan Bengaluru around what you like — and what's actually open.</h2>
          <ul>
            <li><Sparkles size={15} aria-hidden="true" /> Plans built from your neighbourhood and your time</li>
            <li><Sparkles size={15} aria-hidden="true" /> Real places, real travel times, checked hours</li>
            <li><Sparkles size={15} aria-hidden="true" /> Preferences you can change whenever you like</li>
          </ul>
        </div>
        <span className="auth-foot">MADE FOR BENGALURU</span>
      </aside>
      <main className="auth-main">{children}</main>
    </div>
  );
}
