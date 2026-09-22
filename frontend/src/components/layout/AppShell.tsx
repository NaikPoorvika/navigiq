/**
 * App frame: a header on larger screens, a bottom tab bar on phones.
 * Information architecture: Explore · Ask NavigIQ · Plans · Saved
 * (collections and search live under Explore; the account under the avatar).
 */
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { Bookmark, CalendarDays, Compass, Info, LogOut, MessageCircle, Search, Settings } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";

const NAV = [
  { to: "/", label: "Explore", icon: Compass, match: (p: string) => p === "/" || p.startsWith("/search") || p.startsWith("/collections") || p.startsWith("/places") || p.startsWith("/bored") },
  { to: "/ask", label: "Ask NavigIQ", short: "Ask", icon: MessageCircle, match: (p: string) => p.startsWith("/ask") },
  { to: "/plans", label: "Plans", icon: CalendarDays, match: (p: string) => p.startsWith("/plans") },
  { to: "/saved", label: "Saved", icon: Bookmark, match: (p: string) => p.startsWith("/saved") },
] as const;

export function Logo({ className, light }: { className?: string; light?: boolean }) {
  return (
    <Link to="/" className={cn("inline-flex items-center gap-2 rounded-lg", className)} aria-label="NavigIQ home">
      <span className={cn("grid size-8 place-items-center rounded-[10px]", light ? "bg-sand-50 text-primary" : "bg-primary text-primary-foreground")} aria-hidden="true">
        <svg viewBox="0 0 24 24" className="size-[18px]" fill="currentColor">
          <path d="M12 2.5c-4 0-7.2 3.1-7.2 7 0 5.3 7.2 12 7.2 12s7.2-6.7 7.2-12c0-3.9-3.2-7-7.2-7Zm0 9.8a2.9 2.9 0 1 1 0-5.8 2.9 2.9 0 0 1 0 5.8Z" />
        </svg>
      </span>
      <span className={cn("font-display text-lg font-semibold tracking-tight", light ? "text-white" : "text-foreground")}>
        Navig<span className={light ? "text-sand-300" : "text-olive-500"}>IQ</span>
      </span>
    </Link>
  );
}

function AccountMenu({ light }: { light?: boolean }) {
  const { user, isAuthenticated, signOut } = useAuth();
  const navigate = useNavigate();
  if (!isAuthenticated || !user) {
    return (
      <Button asChild size="sm" variant={light ? "secondary" : "outline"}>
        <Link to="/signin">Sign in</Link>
      </Button>
    );
  }
  const initial = (user.display_name || user.email).charAt(0).toUpperCase();
  return (
    <Dropdown.Root>
      <Dropdown.Trigger
        className="grid size-10 place-items-center rounded-full bg-primary font-display text-sm font-semibold text-primary-foreground ring-2 ring-card"
        aria-label="Account menu"
      >
        {initial}
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="end" sideOffset={8} className="z-50 min-w-56 rounded-2xl bg-card p-1.5 shadow-float ring-1 ring-border data-[state=open]:animate-pop">
          <div className="px-3 py-2">
            <p className="text-sm font-semibold">{user.display_name || "Your account"}</p>
            <p className="truncate text-xs text-muted-foreground">{user.email}</p>
          </div>
          <Dropdown.Separator className="my-1 h-px bg-border" />
          <MenuItem onSelect={() => void navigate({ to: "/profile" })} icon={<Settings aria-hidden="true" />}>Profile & preferences</MenuItem>
          <MenuItem onSelect={() => void navigate({ to: "/saved" })} icon={<Bookmark aria-hidden="true" />}>Saved places</MenuItem>
          <MenuItem onSelect={() => void signOut().then(() => navigate({ to: "/" }))} icon={<LogOut aria-hidden="true" />}>Sign out</MenuItem>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

function MenuItem({ children, icon, onSelect }: { children: ReactNode; icon: ReactNode; onSelect: () => void }) {
  return (
    <Dropdown.Item
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm outline-none data-[highlighted]:bg-surface [&_svg]:size-4 [&_svg]:text-muted-foreground"
    >
      {icon}
      {children}
    </Dropdown.Item>
  );
}

export function Header({ overlay }: { overlay?: boolean }) {
  const path = useRouterState({ select: (s) => s.location.pathname });
  return (
    <header
      className={cn(
        "z-40 w-full",
        overlay ? "absolute inset-x-0 top-0" : "sticky top-0 border-b border-border/70 bg-background/85 backdrop-blur-md",
      )}
    >
      <div className="mx-auto flex h-16 max-w-page items-center gap-6 px-4 sm:px-6 lg:px-8">
        <Logo light={overlay} />
        <nav aria-label="Main" className="hidden flex-1 items-center gap-1 md:flex">
          {NAV.map((item) => {
            const active = item.match(path);
            return (
              <Link
                key={item.to}
                to={item.to}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-full px-4 py-2 text-sm font-semibold transition-colors",
                  overlay
                    ? active ? "bg-white/20 text-white" : "text-white/85 hover:bg-white/10 hover:text-white"
                    : active ? "bg-primary-soft text-primary" : "text-muted-foreground hover:bg-surface hover:text-foreground",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Link
            to="/search"
            aria-label="Search places"
            className={cn("grid size-10 place-items-center rounded-full transition-colors",
              overlay ? "text-white hover:bg-white/15" : "text-muted-foreground hover:bg-surface hover:text-foreground")}
          >
            <Search className="size-5" aria-hidden="true" />
          </Link>
          <AccountMenu light={overlay} />
        </div>
      </div>
    </header>
  );
}

export function BottomNav() {
  const path = useRouterState({ select: (s) => s.location.pathname });
  return (
    <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card/95 pb-safe backdrop-blur-md md:hidden">
      <ul className="mx-auto grid max-w-md grid-cols-4 px-2 pt-1.5">
        {NAV.map((item) => {
          const active = item.match(path);
          const Icon = item.icon;
          return (
            <li key={item.to}>
              <Link
                to={item.to}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-2xl text-[11px] font-semibold transition-colors",
                  active ? "text-primary" : "text-muted-foreground",
                )}
              >
                <span className={cn("grid h-7 w-12 place-items-center rounded-full transition-colors", active && "bg-primary-soft")}>
                  <Icon className="size-5" aria-hidden="true" strokeWidth={active ? 2.3 : 1.9} />
                </span>
                {"short" in item ? item.short : item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function SkipLink() {
  return (
    <a href="#main" className="sr-only left-4 top-3 z-[60] rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground focus:not-sr-only focus:fixed">
      Skip to content
    </a>
  );
}

/** Pages render their own <main>; the shell adds navigation and spacing for the tab bar. */
export function AppShell() {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const overlayHeader = path === "/";
  const bare = path.startsWith("/signin") || path.startsWith("/signup");
  if (bare) return (
    <>
      <SkipLink />
      <Outlet />
    </>
  );
  return (
    <div className="min-h-dvh pb-20 md:pb-0">
      <SkipLink />
      <Header overlay={overlayHeader} />
      <Outlet />
      <BottomNav />
    </div>
  );
}

export function PageFooter() {
  return (
    <footer className="mx-auto mt-16 max-w-page px-4 pb-10 text-xs text-muted-foreground sm:px-6 lg:px-8">
      <div className="flex flex-col gap-2 border-t border-border pt-6 sm:flex-row sm:items-center sm:justify-between">
        <p>
          <Info className="mr-1 inline size-3.5 align-[-2px]" aria-hidden="true" />
          NavigIQ plans Bengaluru and up to 90 km around it. Costs are estimates; travel between stops isn't calculated yet.
        </p>
        <p>Place data © OpenStreetMap contributors (ODbL) · Wikipedia (CC BY-SA) · Weather by Open-Meteo</p>
      </div>
    </footer>
  );
}
