/** Small presentational primitives shared across screens. */
import { CircleAlert, RotateCcw } from "lucide-react";
import { forwardRef, type HTMLAttributes, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

// --- chips & badges -----------------------------------------------------------------------------

interface ChipProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean;
  icon?: ReactNode;
  tone?: "default" | "accent" | "info";
}

export const Chip = forwardRef<HTMLButtonElement, ChipProps>(
  ({ selected, icon, tone = "default", className, children, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      aria-pressed={selected ?? undefined}
      className={cn(
        "inline-flex h-10 shrink-0 items-center gap-2 rounded-full border px-4 text-sm font-medium",
        "transition-[background-color,border-color,color,transform] duration-200 active:scale-[0.97]",
        "[&_svg]:size-4 [&_svg]:shrink-0",
        selected
          ? "border-primary bg-primary text-primary-foreground"
          : tone === "accent"
            ? "border-clay-500/30 bg-accent-soft text-clay-700 hover:border-clay-500/60"
            : tone === "info"
              ? "border-sky-700/20 bg-info-soft text-info hover:border-sky-700/40"
              : "border-border bg-card text-foreground hover:border-border-strong hover:bg-sand-50",
        className,
      )}
      {...props}
    >
      {icon}
      {children}
    </button>
  ),
);
Chip.displayName = "Chip";

type BadgeTone = "neutral" | "primary" | "accent" | "info" | "success" | "warning" | "danger" | "glass";

const BADGE: Record<BadgeTone, string> = {
  neutral: "bg-surface text-muted-foreground",
  primary: "bg-primary-soft text-primary",
  accent: "bg-accent-soft text-clay-700",
  info: "bg-info-soft text-info",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  glass: "bg-black/35 text-white backdrop-blur-sm",
};

export function Badge({ tone = "neutral", className, children, ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold leading-none [&_svg]:size-3.5", BADGE[tone], className)}
      {...props}
    >
      {children}
    </span>
  );
}

// --- loading --------------------------------------------------------------------------------------

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden="true" className={cn("skeleton rounded-2xl", className)} {...props} />;
}

/** Status text for work the server is actually doing (screen readers hear it). */
export function WorkingNote({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p role="status" aria-live="polite" className={cn("flex items-center gap-2.5 text-sm text-muted-foreground", className)}>
      <span className="relative flex size-2.5">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-olive-400 opacity-60 motion-reduce:hidden" />
        <span className="relative inline-flex size-2.5 rounded-full bg-primary" />
      </span>
      {children}
    </p>
  );
}

// --- states ---------------------------------------------------------------------------------------

interface StateProps {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
  art?: ReactNode;
}

export function EmptyState({ title, description, action, icon, className, art }: StateProps) {
  return (
    <div className={cn("flex flex-col items-center rounded-3xl border border-dashed border-border-strong bg-card/60 px-6 py-10 text-center", className)}>
      {art}
      {icon && <div className="mb-4 grid size-12 place-items-center rounded-2xl bg-primary-soft text-primary [&_svg]:size-6">{icon}</div>}
      <h3 className="font-display text-lg font-semibold">{title}</h3>
      {description && <p className="mt-2 max-w-md text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ title = "That didn't load", description, onRetry, className }: {
  title?: string; description?: ReactNode; onRetry?: () => void; className?: string;
}) {
  return (
    <div role="alert" className={cn("flex flex-col items-start gap-3 rounded-2xl border border-danger/20 bg-danger-soft/60 p-5 sm:flex-row sm:items-center", className)}>
      <CircleAlert className="size-5 shrink-0 text-danger" aria-hidden="true" />
      <div className="flex-1">
        <p className="font-semibold text-foreground">{title}</p>
        {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
      </div>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          <RotateCcw aria-hidden="true" /> Try again
        </Button>
      )}
    </div>
  );
}

export function SectionHeader({ id, eyebrow, title, description, action, className }: {
  id?: string; eyebrow?: ReactNode; title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string;
}) {
  return (
    <div className={cn("mb-5 flex items-end justify-between gap-4", className)}>
      <div className="min-w-0">
        {eyebrow && <p className="mb-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{eyebrow}</p>}
        <h2 id={id} className="font-display text-2xl font-semibold tracking-tight sm:text-[1.75rem]">{title}</h2>
        {description && <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground sm:text-base">{description}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

// --- form fields -------------------------------------------------------------------------------------

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-12 w-full rounded-xl border border-input bg-card px-4 text-base text-foreground placeholder:text-muted-foreground/80",
        "transition-[border-color,box-shadow] focus:border-ring focus:outline-none focus:ring-4 focus:ring-olive-200/70",
        "aria-[invalid=true]:border-danger aria-[invalid=true]:ring-danger-soft disabled:opacity-60",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "w-full resize-none rounded-xl border border-input bg-card px-4 py-3 text-base text-foreground placeholder:text-muted-foreground/80",
        "focus:border-ring focus:outline-none focus:ring-4 focus:ring-olive-200/70",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

export function Field({ id, label, hint, error, children }: {
  id: string; label: string; hint?: string; error?: string | null; children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-semibold text-foreground">{label}</label>
      {children}
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-sm text-danger">{error}</p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

/** A labelled single-choice control rendered as pills (radio semantics). */
export function Segmented<T extends string>({ label, value, options, onChange, className }: {
  label: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn("inline-flex rounded-full bg-surface p-1", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "h-9 rounded-full px-4 text-sm font-medium transition-colors",
            value === o.value ? "bg-card text-foreground shadow-soft" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="sr-only">{children}</span>;
}
