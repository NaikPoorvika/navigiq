import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AssistantMessage } from "@/components/chat/ChatMessage";
import type { AssistantResponse } from "@/lib/api/types";
import { lalbagh, singleDayPlan, tripPlan } from "@/test/fixtures";
import { renderApp } from "@/test/utils";

function response(patch: Partial<AssistantResponse>): AssistantResponse {
  return {
    conversation_id: "c1", intent: "DISCOVER", text: "Here you go.", data: {}, ui: { type: "message" },
    sources: [], warnings: [], suggestions: [], trace_id: "t1", llm_used: false, llm_available: true,
    ...patch,
  };
}

describe("assistant messages", () => {
  it("turns citation markers into links to the listed sources", async () => {
    const r = response({
      ui: { type: "knowledge_answer" },
      text: "Lalbagh was built by Hyder Ali in 1760. [2] It is known for its glasshouse. [2]",
      sources: [{ n: 2, title: "Lalbagh Botanical Garden", url: "https://en.wikipedia.org/wiki/Lal_Bagh", license: "CC BY-SA 4.0", section: "Summary" }],
    });
    renderApp(<AssistantMessage r={r} onPick={() => {}} idPrefix="m1" />);
    const markers = await screen.findAllByRole("link", { name: "Source 2" });
    expect(markers).toHaveLength(2);   // one per citation in the answer
    expect(markers[0]).toHaveAttribute("href", "#m1-src-2");
    const source = screen.getByRole("link", { name: /Lalbagh Botanical Garden/ });
    expect(source).toHaveAttribute("href", "https://en.wikipedia.org/wiki/Lal_Bagh");
    expect(source).toHaveAttribute("target", "_blank");
    expect(source).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("leaves unknown citation markers as plain text", async () => {
    const r = response({ ui: { type: "knowledge_answer" }, text: "Something [7] unsupported.", sources: [] });
    const { container } = renderApp(<AssistantMessage r={r} onPick={() => {}} idPrefix="m2" />);
    await screen.findByText(/unsupported/);
    expect(container.textContent).toContain("Something [7] unsupported.");
    expect(screen.queryByRole("link", { name: /Source/ })).toBeNull();
  });

  it("shows places as cards with the engine's reasons", async () => {
    const r = response({ ui: { type: "discovery" }, data: { items: [lalbagh] } });
    renderApp(<AssistantMessage r={r} onPick={() => {}} idPrefix="m3" />);
    expect(await screen.findByRole("link", { name: "Lalbagh Botanical Garden" })).toBeInTheDocument();
    expect(screen.getByText("Matches garden")).toBeInTheDocument();
  });

  it("offers suggestions back to the conversation", async () => {
    const onPick = vi.fn();
    const r = response({ ui: { type: "clarification" }, suggestions: [{ label: "Tonight", message: "tonight" }] });
    renderApp(<AssistantMessage r={r} onPick={onPick} idPrefix="m4" />);
    await userEvent.click(await screen.findByRole("button", { name: "Tonight" }));
    expect(onPick).toHaveBeenCalledWith("tonight");
  });

  it("shows a plan with its change summary", async () => {
    const r = response({
      ui: { type: "itinerary" },
      data: {
        itinerary: tripPlan,
        change: ["Day 2: removed Cubbon Park"],
        comparison: {
          added: [], removed: ["Cubbon Park"], retimed: [], kept: [],
          stop_count: { current: 2, variant: 1 },
          estimated_cost: { current: 60, variant: 60, delta: 0 },
          window: { current: ["10:00", "18:00"], variant: ["10:00", "18:00"] },
          span_minutes: { current: 300, variant: 300 },
          days: null, changed_days: [2],
        },
      },
    });
    renderApp(<AssistantMessage r={r} onPick={() => {}} idPrefix="m5" />);
    expect(await screen.findByText("Day 2: removed Cubbon Park")).toBeInTheDocument();
    expect(screen.getByText("Only day 2 changed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open plan/ })).toBeInTheDocument();
  });

  it("puts a what-if beside the current plan and never applies it by itself", async () => {
    const onPick = vi.fn();
    const r = response({
      ui: { type: "itinerary_comparison" },
      data: {
        current: singleDayPlan,
        variant: { ...singleDayPlan, itinerary_id: undefined },
        comparison: {
          added: [], removed: [], retimed: [], kept: [],
          stop_count: { current: 2, variant: 2 },
          estimated_cost: { current: 60, variant: 40, delta: -20 },
          window: { current: ["10:00", "18:00"], variant: ["10:00", "18:00"] },
          span_minutes: { current: 300, variant: 280 },
          days: null, changed_days: null,
        },
        change: ["Budget set to ₹500"],
      },
    });
    renderApp(<AssistantMessage r={r} onPick={onPick} idPrefix="m6" />);
    expect(await screen.findByText("Current plan")).toBeInTheDocument();
    expect(screen.getByText("What if…")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Keep current/ }));
    expect(onPick).toHaveBeenCalledWith("Keep my current plan");
    await userEvent.click(screen.getByRole("button", { name: /Apply this version/ }));
    expect(onPick).toHaveBeenCalledWith("Apply the what-if");
  });

  it("passes the server's warnings through", async () => {
    const r = response({ warnings: ["Weather is unavailable, so the plan ignores it."] });
    renderApp(<AssistantMessage r={r} onPick={() => {}} idPrefix="m7" />);
    expect(await screen.findByText(/Weather is unavailable/)).toBeInTheDocument();
  });
});
