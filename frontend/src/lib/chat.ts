/**
 * Conversation state for Ask NavigIQ. The server owns the conversation
 * (history, the active plan, pending clarifications); this hook keeps the id,
 * restores the thread after a reload and sends messages.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { AssistantResponse } from "@/lib/api/types";

const KEY = "navigiq.conversation";

export type ChatTurn =
  | { id: string; role: "user"; text: string; pending?: boolean; failed?: boolean }
  | { id: string; role: "assistant"; response: AssistantResponse };

interface HistoryResponse {
  conversation_id: string;
  messages: { role: "user" | "assistant"; content: string; payload: AssistantResponse | null; created_at: string }[];
}

function storedId(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function storeId(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(KEY, id);
    else window.localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}

let seq = 0;
const nextId = () => `t${Date.now().toString(36)}${(seq++).toString(36)}`;

export function useConversation() {
  const qc = useQueryClient();
  const [conversationId, setConversationId] = useState<string | null>(() => storedId());
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [restored, setRestored] = useState(false);

  const history = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.get<HistoryResponse>(`/assistant/conversations/${conversationId}`),
    enabled: Boolean(conversationId) && !restored,
    retry: false,
    staleTime: Infinity,
  });

  useEffect(() => {
    if (restored) return;
    if (history.data) {
      const restoredTurns: ChatTurn[] = history.data.messages.map((m) =>
        m.role === "assistant" && m.payload
          ? { id: nextId(), role: "assistant", response: m.payload }
          : { id: nextId(), role: "user", text: m.content },
      );
      setTurns(restoredTurns);
      setRestored(true);
    } else if (history.isError) {
      // The conversation is gone or belongs to another session: start fresh.
      storeId(null);
      setConversationId(null);
      setRestored(true);
    } else if (!conversationId) {
      setRestored(true);
    }
  }, [history.data, history.isError, conversationId, restored]);

  const idRef = useRef<string | null>(conversationId);
  idRef.current = conversationId;

  const send = useMutation({
    mutationFn: ({ text, convId }: { text: string; turnId: string; convId: string | null }) => endpoints.chat(text, convId),
    onMutate: ({ text, turnId }) => {
      setTurns((t) => [...t.filter((x) => !(x.role === "user" && x.failed)), { id: turnId, role: "user", text, pending: true }]);
    },
    onSuccess: (response, { turnId }) => {
      if (response.conversation_id !== idRef.current) {
        idRef.current = response.conversation_id;
        setConversationId(response.conversation_id);
        storeId(response.conversation_id);
      }
      setTurns((t) => [
        ...t.map((x) => (x.id === turnId && x.role === "user" ? { ...x, pending: false } : x)),
        { id: nextId(), role: "assistant", response },
      ]);
      // Plans or saved places may have changed through the conversation.
      if (["itinerary", "itinerary_comparison"].includes(response.ui.type)) void qc.invalidateQueries({ queryKey: ["plans"] });
      if (response.intent === "SAVE_PLACE") void qc.invalidateQueries({ queryKey: ["saved"] });
    },
    onError: (err, { turnId }) => {
      if (err instanceof ApiError && err.code === "NOT_FOUND") {
        storeId(null);
        setConversationId(null);
      }
      setTurns((t) => t.map((x) => (x.id === turnId && x.role === "user" ? { ...x, pending: false, failed: true } : x)));
    },
  });

  const ask = useCallback((text: string, opts: { fresh?: boolean } = {}) => {
    const clean = text.trim().slice(0, 2000);
    if (!clean || send.isPending) return;
    if (opts.fresh) {
      idRef.current = null;
      storeId(null);
      setConversationId(null);
      setTurns([]);
    }
    send.mutate({ text: clean, turnId: nextId(), convId: idRef.current });
  }, [send]);

  const reset = useCallback(() => {
    idRef.current = null;
    storeId(null);
    setConversationId(null);
    setTurns([]);
    send.reset();
  }, [send]);

  const lastError = send.error instanceof ApiError ? send.error : send.error ? new ApiError(0, "UNKNOWN", "Something went wrong.") : null;
  const failedText = useMemo(() => {
    const f = [...turns].reverse().find((t) => t.role === "user" && t.failed);
    return f && f.role === "user" ? f.text : null;
  }, [turns]);

  return {
    conversationId, turns, ask, reset, restoring: !restored, sending: send.isPending,
    pendingText: send.isPending ? send.variables?.text ?? null : null, lastError, failedText,
  };
}

/**
 * What NavigIQ is doing while a message is in flight. The copy follows the
 * shape of the request and says only what that workflow really does.
 */
export function workingCopy(text: string | null, seconds: number): string {
  const t = (text ?? "").toLowerCase();
  const planning = /\b(plan|itinerary|trip|schedule|day out|weekend)\b/.test(t);
  const changing = /\b(remove|replace|swap|cheaper|relaxed|later|earlier|add|instead|what if)\b/.test(t);
  const question = /^(what|why|who|when|how|is|are|does|do|can|tell me)\b/.test(t) || t.endsWith("?");
  if (changing && !planning) {
    return seconds < 3 ? "Applying your change…" : "Re-planning just what changed and re-checking hours and budget…";
  }
  if (planning) {
    if (seconds < 3) return "Reading your request…";
    if (seconds < 8) return "Choosing places and checking opening hours and your budget…";
    return "Still arranging stops. Multi-day plans take a little longer…";
  }
  if (question) return seconds < 4 ? "Looking through NavigIQ's sources…" : "Checking the answer against its sources…";
  return seconds < 4 ? "Finding places that fit…" : "Ranking what fits best…";
}
