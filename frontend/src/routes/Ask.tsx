/**
 * Ask NavigIQ — one conversation that discovers, answers and plans. The
 * server keeps the conversation (active plan, pending questions); results
 * render as real cards, plans open in the planner, answers show sources.
 */
import { useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowUp, BookOpen, CalendarRange, Compass, Dices, Map as MapIcon, RotateCcw, SquarePen, WifiOff, X } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { AssistantMessage } from "@/components/chat/ChatMessage";
import { LazyMap } from "@/components/map/LazyMap";
import { Button } from "@/components/ui/button";
import { BottomSheet } from "@/components/ui/overlay";
import { ErrorState, WorkingNote } from "@/components/ui/primitives";
import type { ScoredPoi } from "@/lib/api/types";
import { useConversation, workingCopy } from "@/lib/chat";
import { cn } from "@/lib/cn";
import { useDocumentTitle, useElapsed, useIsDesktop } from "@/lib/hooks";
import { rememberPrompt } from "@/lib/recent";

const STARTERS = [
  { icon: Compass, title: "Discover", prompts: ["Quiet places to read this afternoon", "Street food near Basavanagudi", "Something adventurous outside the city"] },
  { icon: BookOpen, title: "Understand", prompts: ["Why is Lalbagh famous?", "What's the story behind Bangalore Palace?", "Is Cubbon Park good in the evening?"] },
  { icon: CalendarRange, title: "Plan", prompts: ["Plan Saturday with a lake, lunch and a museum under ₹1500", "A relaxed evening for two in Indiranagar", "Plan 2 days with heritage and good food"] },
];

function Composer({ onSend, busy, autoFocus }: { onSend: (t: string) => void; busy: boolean; autoFocus?: boolean }) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);
  const send = () => {
    const t = value.trim();
    if (!t || busy) return;
    onSend(t);
    setValue("");
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };
  return (
    <form
      onSubmit={(e) => { e.preventDefault(); send(); }}
      className="flex items-end gap-2 rounded-[1.75rem] bg-card p-2 pl-4 shadow-lift ring-1 ring-border focus-within:ring-2 focus-within:ring-ring"
    >
      <label htmlFor="ask-input" className="sr-only">Message NavigIQ</label>
      <textarea
        id="ask-input"
        ref={ref}
        rows={1}
        value={value}
        maxLength={2000}
        autoFocus={autoFocus}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKey}
        placeholder="Ask about places, plans, or Bengaluru…"
        className="max-h-40 min-h-11 flex-1 resize-none bg-transparent py-2.5 text-[15px] leading-6 placeholder:text-muted-foreground/85 focus:outline-none"
      />
      <button
        type="submit"
        disabled={!value.trim() || busy}
        aria-label="Send message"
        className="grid size-11 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground transition-[opacity,transform] hover:bg-primary-hover active:scale-95 disabled:opacity-40"
      >
        <ArrowUp className="size-5" aria-hidden="true" />
      </button>
    </form>
  );
}

function Starters({ onPick }: { onPick: (t: string) => void }) {
  const navigate = useNavigate();
  return (
    <div className="animate-rise">
      <div className="mb-8 text-center">
        <div className="mx-auto mb-4 grid size-14 place-items-center rounded-2xl bg-primary text-primary-foreground shadow-lift">
          <svg viewBox="0 0 24 24" className="size-7" fill="currentColor" aria-hidden="true">
            <path d="M12 2.5c-4 0-7.2 3.1-7.2 7 0 5.3 7.2 12 7.2 12s7.2-6.7 7.2-12c0-3.9-3.2-7-7.2-7Zm0 9.8a2.9 2.9 0 1 1 0-5.8 2.9 2.9 0 0 1 0 5.8Z" />
          </svg>
        </div>
        <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">Ask NavigIQ</h1>
        <p className="mx-auto mt-3 max-w-lg text-muted-foreground">
          Places to go, what they're about, or a plan for the day — in English, Hinglish or Kannada.
          Facts, costs and timings come from NavigIQ's data, never from guesswork.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {STARTERS.map((g) => {
          const Icon = g.icon;
          return (
            <section key={g.title} className="rounded-3xl bg-card p-4 shadow-soft ring-1 ring-border/60">
              <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
                <Icon className="size-4" aria-hidden="true" /> {g.title}
              </h2>
              <ul className="space-y-1">
                {g.prompts.map((p) => (
                  <li key={p}>
                    <button type="button" onClick={() => onPick(p)} className="w-full rounded-xl px-2.5 py-2 text-left text-[15px] transition-colors hover:bg-surface">
                      {p}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
      <div className="mt-5 flex justify-center">
        <Button variant="accent" onClick={() => void navigate({ to: "/bored" })}>
          <Dices aria-hidden="true" /> I'm bored — surprise me
        </Button>
      </div>
    </div>
  );
}

function UserBubble({ text, pending, failed, onRetry }: { text: string; pending?: boolean; failed?: boolean; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-end">
      <p className={cn("max-w-[85%] whitespace-pre-wrap rounded-3xl rounded-br-lg bg-primary px-4 py-2.5 text-[15px] text-primary-foreground", pending && "opacity-80")}>
        {text}
      </p>
      {failed && (
        <button type="button" onClick={onRetry} className="mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-danger hover:underline">
          <RotateCcw className="size-3" aria-hidden="true" /> Not sent — tap to retry
        </button>
      )}
    </div>
  );
}

export function AskPage() {
  useDocumentTitle("Ask NavigIQ");
  const search = useSearch({ from: "/ask" });
  const navigate = useNavigate();
  const conv = useConversation();
  const desktop = useIsDesktop();
  const elapsed = useElapsed(conv.sending);
  const [mapItems, setMapItems] = useState<ScoredPoi[] | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const handledQ = useRef<string | null>(null);

  // A question from the home screen: start (or continue) with it once.
  useEffect(() => {
    if (conv.restoring || !search.q || handledQ.current === search.q) return;
    handledQ.current = search.q;
    conv.ask(search.q, { fresh: Boolean(search.new) });
    void navigate({ to: "/ask", search: {}, replace: true });
  }, [conv, search.q, search.new, navigate]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [conv.turns.length, conv.sending]);

  const ask = (t: string) => {
    rememberPrompt(t);
    conv.ask(t);
  };
  const lastAssistant = [...conv.turns].reverse().find((t) => t.role === "assistant");
  const llmOffline = lastAssistant?.role === "assistant" && !lastAssistant.response.llm_available;
  const empty = !conv.turns.length && !conv.sending && !conv.restoring;

  return (
    <div className="mx-auto flex w-full max-w-page gap-6 px-4 sm:px-6 lg:px-8">
      <main id="main" className="flex min-h-[calc(100dvh-4rem)] min-w-0 flex-1 flex-col pb-24 md:pb-6">
        <div className="flex items-center justify-between py-4">
          <p className="text-sm font-semibold text-muted-foreground">{empty ? "" : "Conversation"}</p>
          {!empty && (
            <Button variant="ghost" size="sm" onClick={() => { conv.reset(); setMapItems(null); }}>
              <SquarePen aria-hidden="true" /> New chat
            </Button>
          )}
        </div>

        {llmOffline && (
          <p className="mb-4 flex items-start gap-2 rounded-2xl bg-info-soft px-4 py-3 text-sm text-info">
            <WifiOff className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            The language model is offline, so NavigIQ is using its rule-based understanding. Discovery, facts and plans still work; replies are simpler.
          </p>
        )}

        <div className="flex-1">
          {conv.restoring ? (
            <WorkingNote className="py-10">Restoring your conversation…</WorkingNote>
          ) : empty ? (
            <div className="mx-auto max-w-4xl py-6 sm:py-10"><Starters onPick={ask} /></div>
          ) : (
            <ol className="mx-auto max-w-3xl space-y-6" aria-live="polite" aria-relevant="additions">
              {conv.turns.map((t) => (
                <li key={t.id}>
                  {t.role === "user" ? (
                    <UserBubble text={t.text} pending={t.pending} failed={t.failed} onRetry={() => conv.ask(t.text)} />
                  ) : (
                    <div className="flex gap-3">
                      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-primary-soft text-primary" aria-hidden="true">
                        <svg viewBox="0 0 24 24" className="size-4" fill="currentColor"><path d="M12 2.5c-4 0-7.2 3.1-7.2 7 0 5.3 7.2 12 7.2 12s7.2-6.7 7.2-12c0-3.9-3.2-7-7.2-7Zm0 9.8a2.9 2.9 0 1 1 0-5.8 2.9 2.9 0 0 1 0 5.8Z" /></svg>
                      </span>
                      <div className="min-w-0 flex-1">
                        <span className="sr-only">NavigIQ:</span>
                        <AssistantMessage r={t.response} onPick={ask} busy={conv.sending} idPrefix={t.id} onShowMap={(items) => setMapItems(items)} />
                      </div>
                    </div>
                  )}
                </li>
              ))}
              {conv.sending && (
                <li className="pl-11"><WorkingNote>{workingCopy(conv.pendingText, elapsed)}</WorkingNote></li>
              )}
              {conv.lastError && !conv.sending && (
                <li>
                  <ErrorState
                    title={conv.lastError.code === "RATE_LIMITED" ? "Slow down a little" : "That message didn't go through"}
                    description={conv.lastError.isNetwork ? "NavigIQ can't be reached. Check your connection." : conv.lastError.message}
                    onRetry={conv.failedText ? () => conv.ask(conv.failedText!) : undefined}
                  />
                </li>
              )}
            </ol>
          )}
          <div ref={endRef} />
        </div>

        <div className="sticky bottom-20 z-30 mx-auto mt-6 w-full max-w-3xl md:bottom-4">
          <Composer onSend={ask} busy={conv.sending} autoFocus={desktop && empty} />
          <p className="mt-2 text-center text-[11px] text-muted-foreground">
            Costs are estimates. Travel between stops isn't calculated yet — plans leave buffers instead.
          </p>
        </div>
      </main>

      {!desktop && (
        <BottomSheet open={Boolean(mapItems)} onOpenChange={(o) => !o && setMapItems(null)} title="On the map"
          description="Pins show where each place is. NavigIQ doesn't draw routes.">
          {mapItems && (
            <LazyMap
              label="Map of the places in this answer"
              className="h-[60dvh] overflow-hidden rounded-2xl ring-1 ring-border"
              pins={mapItems.map((p, i) => ({ id: p.id, lat: p.lat, lon: p.lon, title: p.name, label: i + 1 }))}
            />
          )}
        </BottomSheet>
      )}
      {desktop && mapItems && (
        <aside className="sticky top-20 hidden h-[calc(100dvh-6rem)] w-[26rem] shrink-0 flex-col py-4 lg:flex" aria-label="Map of results">
          <div className="mb-2 flex items-center justify-between">
            <p className="flex items-center gap-1.5 text-sm font-semibold"><MapIcon className="size-4" aria-hidden="true" /> On the map</p>
            <Button variant="ghost" size="icon-sm" onClick={() => setMapItems(null)} aria-label="Close map"><X aria-hidden="true" /></Button>
          </div>
          <LazyMap
            label="Map of the places in this answer"
            className="min-h-0 flex-1 overflow-hidden rounded-3xl ring-1 ring-border"
            pins={mapItems.map((p, i) => ({ id: p.id, lat: p.lat, lon: p.lon, title: p.name, label: i + 1 }))}
          />
        </aside>
      )}
    </div>
  );
}
