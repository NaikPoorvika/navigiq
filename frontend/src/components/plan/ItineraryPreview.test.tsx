import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChangeSummary } from "@/components/plan/ChangeSummary";
import { ItineraryPreview } from "@/components/plan/ItineraryPreview";
import { singleDayPlan, tripPlan } from "@/test/fixtures";
import { renderApp } from "@/test/utils";

describe("itinerary preview", () => {
  it("shows a single day with its window and total", async () => {
    renderApp(<ItineraryPreview it={singleDayPlan} />);
    expect(await screen.findByText("Garden & Museum day")).toBeInTheDocument();
    expect(screen.getByText(/Saturday, 26 Sep · 10 am–6 pm/)).toBeInTheDocument();
    expect(screen.getByText("₹60–₹120")).toBeInTheDocument();
    expect(screen.getByText(/excludes transport/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open plan/ })).toBeInTheDocument();
  });

  it("groups a trip by day and numbers stops within each day", async () => {
    renderApp(<ItineraryPreview it={tripPlan} />);
    expect(await screen.findByText(/Day 1 · Sat 26 Sep · Shanti Nagar/)).toBeInTheDocument();
    expect(screen.getByText(/Day 2 · Sun 27 Sep · Sampangi Rama Nagar/)).toBeInTheDocument();
    expect(screen.getByText("Sat 26 Sep – Sun 27 Sep")).toBeInTheDocument();
    // both days start with stop 1
    expect(screen.getAllByText("1")).toHaveLength(2);
  });
});

describe("change summary", () => {
  const comparison = {
    added: ["Cubbon Park"],
    removed: ["Bangalore Palace"],
    retimed: ["Lalbagh Botanical Garden"],
    kept: ["Lalbagh Botanical Garden"],
    stop_count: { current: 3, variant: 3 },
    estimated_cost: { current: 800, variant: 600, delta: -200 },
    window: { current: ["10:00", "18:00"] as [string, string], variant: ["10:00", "18:00"] as [string, string] },
    span_minutes: { current: 300, variant: 280 },
    days: null,
    changed_days: null,
  };

  it("spells out what was removed, added and what it costs now", async () => {
    renderApp(<ChangeSummary comparison={comparison} summary={["Removed Bangalore Palace"]} />);
    expect(await screen.findByText("Bangalore Palace")).toBeInTheDocument();
    expect(screen.getByText("Cubbon Park")).toBeInTheDocument();
    expect(screen.getByText(/New times for Lalbagh/)).toBeInTheDocument();
    expect(screen.getByText("−₹200")).toBeInTheDocument();
    expect(screen.getByText("Removed Bangalore Palace")).toBeInTheDocument();
  });

  it("names the days that changed in a trip", async () => {
    renderApp(<ChangeSummary comparison={{ ...comparison, changed_days: [2] }} />);
    expect(await screen.findByText("Only day 2 changed")).toBeInTheDocument();
  });

  it("is honest when nothing moved", async () => {
    renderApp(<ChangeSummary comparison={{ ...comparison, added: [], removed: [], retimed: [] }} />);
    expect(await screen.findByText(/The same places still fit best/)).toBeInTheDocument();
  });
});
