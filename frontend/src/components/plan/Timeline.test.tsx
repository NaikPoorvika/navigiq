import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ItineraryTimeline } from "@/components/plan/ItineraryTimeline";
import { WhatIfCompare } from "@/components/plan/WhatIfCompare";
import { singleDayPlan, tripPlan } from "@/test/fixtures";
import { renderApp } from "@/test/utils";

const noop = () => {};

function timeline(it = tripPlan, extra: Partial<Parameters<typeof ItineraryTimeline>[0]> = {}) {
  return (
    <ItineraryTimeline
      it={it}
      spec={it.days?.[0]?.spec ?? tripPlan.days![0]!.spec}
      selectedSeq={null}
      onSelectStop={noop}
      onRun={noop}
      onRemove={noop}
      onReplace={noop}
      updatingDay={null}
      openDays={[1, 2]}
      onToggleDay={noop}
      {...extra}
    />
  );
}

describe("itinerary timeline", () => {
  it("renders one section per trip day with its title and stops", async () => {
    renderApp(timeline());
    const day1 = await screen.findByRole("region", { name: "Day 1" });
    const day2 = screen.getByRole("region", { name: "Day 2" });
    expect(within(day1).getByRole("heading", { name: "Shanti Nagar" })).toBeInTheDocument();
    expect(within(day1).getByRole("link", { name: /Lalbagh Botanical Garden/ })).toBeInTheDocument();
    expect(within(day2).getByRole("link", { name: /Cubbon Park/ })).toBeInTheDocument();
  });

  it("warns when a stop's hours aren't verified", async () => {
    renderApp(timeline());
    expect((await screen.findAllByText(/Opening hours aren't verified/)).length).toBeGreaterThan(0);
  });

  it("scopes quick changes to the day they were chosen on", async () => {
    const onRun = vi.fn();
    const user = userEvent.setup();
    renderApp(timeline(tripPlan, { onRun }));
    await user.click(await screen.findByRole("button", { name: "Change day 1" }));
    await user.click(await screen.findByRole("menuitem", { name: /More relaxed/ }));
    expect(onRun).toHaveBeenCalledWith(expect.objectContaining({ id: "relaxed" }), 1);
  });

  it("disables a change that is already true for that day", async () => {
    const user = userEvent.setup();
    renderApp(timeline());
    await user.click(await screen.findByRole("button", { name: "Change day 2" }));
    const item = await screen.findByRole("menuitem", { name: /More relaxed/ });
    expect(item).toHaveAttribute("data-disabled");
  });

  it("removes a stop by its day and day-local number", async () => {
    const onRemove = vi.fn();
    const user = userEvent.setup();
    renderApp(timeline(tripPlan, { onRemove }));
    await user.click(await screen.findByRole("button", { name: /Change stop 1, Cubbon Park/ }));
    await user.click(await screen.findByRole("menuitem", { name: /Remove from plan/ }));
    expect(onRemove).toHaveBeenCalledWith(2, 1, "Cubbon Park");
  });

  it("shows the re-planning status on the day being changed", async () => {
    renderApp(timeline(tripPlan, { updatingDay: 2, updatingText: "Slowing down day 2… keeping 10:00–18:00." }));
    const day2 = await screen.findByRole("region", { name: "Day 2" });
    expect(within(day2).getByRole("status")).toHaveTextContent("Slowing down day 2");
    expect(day2).toHaveAttribute("aria-busy", "true");
  });

  it("offers no changes in a read-only (old version) view", async () => {
    renderApp(timeline(singleDayPlan, { readOnly: true, spec: tripPlan.days![0]!.spec }));
    await screen.findByRole("link", { name: /Lalbagh Botanical Garden/ });
    expect(screen.queryByRole("button", { name: /^Change stop/ })).toBeNull();
  });
});

describe("what-if comparison", () => {
  const variant = { ...singleDayPlan, stops: [singleDayPlan.stops[0]!] };
  const comparison = {
    added: [], removed: ["Cubbon Park"], retimed: [], kept: ["Lalbagh Botanical Garden"],
    stop_count: { current: 2, variant: 1 },
    estimated_cost: { current: 60, variant: 60, delta: 0 },
    window: { current: ["10:00", "18:00"] as [string, string], variant: ["10:00", "18:00"] as [string, string] },
    span_minutes: { current: 300, variant: 90 },
    days: null, changed_days: null,
  };

  it("keeps the current plan unless the person applies the variant", async () => {
    const onKeep = vi.fn();
    const onApply = vi.fn();
    const user = userEvent.setup();
    renderApp(<WhatIfCompare current={singleDayPlan} variant={variant} comparison={comparison} summary={["Fewer stops"]} onKeep={onKeep} onApply={onApply} />);
    expect(await screen.findByText("If you apply this")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Keep current/ }));
    expect(onKeep).toHaveBeenCalledOnce();
    expect(onApply).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /Apply what-if/ }));
    expect(onApply).toHaveBeenCalledOnce();
  });
});
