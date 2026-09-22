import { useNavigate, useRouterState } from "@tanstack/react-router";
import { Bookmark, BookmarkCheck } from "lucide-react";
import { toast } from "sonner";
import type { PoiCard } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { useSavedIds, useToggleSave } from "@/lib/queries";

/** Saving needs an account (the backend keeps saved places per user). */
export function SaveButton({ poi, variant = "icon", className }: {
  poi: PoiCard; variant?: "icon" | "pill" | "overlay"; className?: string;
}) {
  const { isAuthenticated } = useAuth();
  const savedIds = useSavedIds();
  const toggle = useToggleSave();
  const navigate = useNavigate();
  const location = useRouterState({ select: (s) => s.location.href });
  const saved = savedIds.has(poi.id);

  const onClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isAuthenticated) {
      toast("Sign in to save places", {
        description: "Saved places follow you across devices. Browsing and planning work without an account.",
        action: { label: "Sign in", onClick: () => void navigate({ to: "/signin", search: { redirect: location } }) },
      });
      return;
    }
    toggle.mutate({ poi, save: !saved });
  };

  const label = saved ? `Remove ${poi.name} from saved places` : `Save ${poi.name}`;
  const Icon = saved ? BookmarkCheck : Bookmark;

  if (variant === "pill") {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-pressed={saved}
        aria-label={label}
        className={cn(
          "inline-flex h-11 items-center gap-2 rounded-full border px-5 text-sm font-semibold transition-colors",
          saved ? "border-primary bg-primary-soft text-primary" : "border-border-strong bg-card hover:bg-surface",
          className,
        )}
      >
        <Icon className={cn("size-4", saved && "fill-current")} aria-hidden="true" />
        {saved ? "Saved" : "Save"}
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={saved}
      aria-label={label}
      title={saved ? "Saved" : "Save"}
      className={cn(
        "grid size-10 place-items-center rounded-full transition-[background-color,transform] active:scale-90",
        variant === "overlay"
          ? "bg-card/90 text-foreground shadow-soft backdrop-blur hover:bg-card"
          : "text-muted-foreground hover:bg-surface hover:text-foreground",
        saved && "text-primary",
        className,
      )}
    >
      <Icon className={cn("size-[18px]", saved && "fill-current")} aria-hidden="true" />
    </button>
  );
}
