import type { ReactNode } from "react";
import { Compass, Sparkles, UserRound } from "lucide-react";
import { href } from "../lib/router";
import { useAccount } from "../store/account";

const NAV = [
  { path: "/", key: "", label: "Home" },
  { path: "/plan", key: "plan", label: "Plan a trip" },
  { path: "/plans", key: "plans", label: "Your plans" },
];

export default function Shell({ active, children }: { active: string; children: ReactNode }) {
  const { profile, signedIn } = useAccount();

  return (
    <div className="app">
      <header className="app-header">
        <a className="brand" href={href("/")}>
          <span className="brand-mark"><Compass size={20} aria-hidden="true" /></span>
          <span className="brand-name">NavigIQ</span>
        </a>

        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <a key={n.key} className={`nav-link ${active === n.key ? "active" : ""}`} href={href(n.path)}>
              {n.label}
            </a>
          ))}
          <a className={`nav-ai ${active === "discover" ? "active" : ""}`} href={href("/discover")}>
            <Sparkles size={15} aria-hidden="true" /> Plan with AI
          </a>
        </nav>

        <div className="account">
          {signedIn && profile ? (
            <a className="avatar-link" href={href("/profile")}>
              <span className="avatar">{profile.name.charAt(0).toUpperCase() || <UserRound size={16} />}</span>
              <span className="avatar-name">{profile.name.split(" ")[0]}</span>
            </a>
          ) : (
            <>
              <a className="nav-link" href={href("/signin")}>Sign in</a>
              <a className="btn-small" href={href("/welcome")}>Get started</a>
            </>
          )}
        </div>
      </header>

      <main>{children}</main>

      <footer className="app-footer">
        Map and place data © OpenStreetMap contributors, ODbL · Weather: Open-Meteo ·
        Photos: Wikimedia Commons contributors · <a href={href("/credits")}>Credits</a>
      </footer>
    </div>
  );
}
