import { ArrowUp, Sparkles } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { cn } from "@/lib/cn";
import { useRotating } from "@/lib/hooks";

/** Example requests. They are examples of what to ASK, not claims about places. */
export const EXAMPLE_PROMPTS = [
  "A quiet café to read in Jayanagar",
  "Plan a romantic evening under ₹2,000",
  "A weekend with a hill and a lake",
  "What's Lalbagh famous for?",
  "Something fun indoors, it's raining",
  "Plan 3 days with museums, gardens and good food",
  "Hidden gems near Basavanagudi",
] as const;

interface Props {
  onSubmit: (text: string) => void;
  variant?: "hero" | "inline";
  busy?: boolean;
  autoFocus?: boolean;
  label?: string;
  className?: string;
  defaultValue?: string;
}

export function AskBar({ onSubmit, variant = "inline", busy, autoFocus, label = "Ask NavigIQ", className, defaultValue = "" }: Props) {
  const [value, setValue] = useState(defaultValue);
  const example = useRotating(EXAMPLE_PROMPTS, 4000);
  const id = useId();
  const hero = variant === "hero";

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = value.trim();
    if (!text || busy) return;
    onSubmit(text);
    setValue("");
  };

  return (
    <form
      onSubmit={submit}
      role="search"
      className={cn(
        "group relative flex items-center gap-2 rounded-full bg-card transition-shadow",
        hero ? "h-16 pl-5 pr-2 shadow-float ring-1 ring-black/5 sm:h-[4.25rem]" : "h-14 pl-4 pr-1.5 shadow-soft ring-1 ring-border",
        "focus-within:ring-2 focus-within:ring-ring",
        className,
      )}
    >
      <Sparkles className={cn("shrink-0 text-accent", hero ? "size-5" : "size-[18px]")} aria-hidden="true" />
      <label htmlFor={id} className="sr-only">{label}</label>
      <input
        id={id}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={example ? `Try “${example}”` : "Ask anything about Bengaluru"}
        maxLength={2000}
        autoComplete="off"
        enterKeyHint="send"
        autoFocus={autoFocus}
        className={cn(
          "min-w-0 flex-1 bg-transparent text-foreground placeholder:text-muted-foreground/85 focus:outline-none",
          hero ? "text-base sm:text-lg" : "text-[15px]",
        )}
      />
      <button
        type="submit"
        disabled={!value.trim() || busy}
        aria-label="Send"
        className={cn(
          "grid shrink-0 place-items-center rounded-full bg-primary text-primary-foreground transition-[background-color,transform,opacity]",
          "hover:bg-primary-hover active:scale-95 disabled:opacity-40",
          hero ? "size-12 sm:size-[3.25rem]" : "size-11",
        )}
      >
        <ArrowUp className="size-5" aria-hidden="true" />
      </button>
    </form>
  );
}
