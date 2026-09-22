import { describe, expect, it } from "vitest";
import { singleDayPlan, tripPlan } from "@/test/fixtures";
import { daysOf, isTrip, localSeq } from "@/lib/plan";
import { keptConstraints, quickActions } from "@/lib/planActions";
import { workingCopy } from "@/lib/chat";

describe("itinerary shape", () => {
  it("treats a single day as one day", () => {
    expect(isTrip(singleDayPlan)).toBe(false);
    const days = daysOf(singleDayPlan);
    expect(days).toHaveLength(1);
    expect(days[0]!.stops).toHaveLength(2);
  });

  it("groups a trip by day and keeps per-day numbering", () => {
    expect(isTrip(tripPlan)).toBe(true);
    const days = daysOf(tripPlan);
    expect(days.map((d) => d.day)).toEqual([1, 2]);
    expect(days[1]!.date).toBe("2026-09-27");
    expect(days[1]!.stops.map(localSeq)).toEqual([1]);
    // the trip-wide sequence is still unique
    expect(tripPlan.stops.map((s) => s.seq)).toEqual([1, 2]);
  });
});

describe("quick actions", () => {
  it("prices 'cheaper' from the plan's own estimate", () => {
    const a = quickActions(singleDayPlan, tripPlan.days![0]!.spec).find((x) => x.id === "cheaper")!;
    // 60 typical -> 75% -> rounded down to a multiple of 50
    expect(a.ops).toEqual([{ op: "set_budget", amount: 0 }]);
    expect(a.disabled).toBe(false);
  });

  it("scopes a change to one day of a trip", () => {
    const a = quickActions(tripPlan, tripPlan.days![0]!.spec, 2).find((x) => x.id === "relaxed")!;
    expect(a.ops[0]).toMatchObject({ op: "set_pace", pace: "relaxed", day: 2 });
  });

  it("disables what is already true", () => {
    const day2 = tripPlan.days![1]!.spec; // pace relaxed
    const a = quickActions(tripPlan, day2, 2).find((x) => x.id === "relaxed")!;
    expect(a.disabled).toBe("Already relaxed");
  });

  it("lists what a change keeps, including the other days", () => {
    const kept = keptConstraints(tripPlan, tripPlan.days![0]!.spec, 1);
    expect(kept).toContain("10:00–18:00");
    expect(kept).toContain("budget ₹2000");
    expect(kept).toContain("the other days as they are");
  });
});

describe("working copy", () => {
  it("describes what the planner is doing for a plan request", () => {
    expect(workingCopy("Plan Saturday with a lake", 0)).toMatch(/Reading/);
    expect(workingCopy("Plan Saturday with a lake", 5)).toMatch(/opening hours/);
  });

  it("describes a change and a question differently", () => {
    expect(workingCopy("remove the museum", 0)).toMatch(/change/i);
    expect(workingCopy("why is Lalbagh famous?", 0)).toMatch(/sources/i);
  });
});
