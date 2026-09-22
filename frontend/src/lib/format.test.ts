import { describe, expect, it } from "vitest";
import {
  addDays, clock, costLabel, costShort, dateLabel, dateRangeLabel, distanceLabel, minutesLabel,
  plural, relativeDay, signedRupees,
} from "@/lib/format";

describe("money", () => {
  it("says Free only when the top of the range is zero", () => {
    expect(costLabel({ min: 0, typical: 0, max: 0 })).toBe("Free");
    expect(costLabel({ min: 0, typical: 30, max: 60 })).toBe("₹0–₹60");
    expect(costShort({ min: 0, typical: 30, max: 60 })).toBe("~₹30");
  });

  it("never claims a cost it doesn't have", () => {
    expect(costLabel(null)).toBe("Cost unknown");
    expect(costShort(undefined)).toBe("—");
  });

  it("formats rupees in the Indian grouping", () => {
    expect(costLabel({ min: 100000, typical: 100000, max: 100000 })).toBe("~₹1,00,000");
  });

  it("shows the direction of a change", () => {
    expect(signedRupees(-200)).toBe("−₹200");
    expect(signedRupees(150)).toBe("+₹150");
    expect(signedRupees(0)).toBe("same cost");
  });
});

describe("time", () => {
  it("renders 24h API times as 12h local", () => {
    expect(clock("14:30")).toBe("2:30 pm");
    expect(clock("09:00")).toBe("9 am");
    expect(clock("00:15")).toBe("12:15 am");
    expect(clock("12:00")).toBe("12 pm");
  });

  it("reads durations", () => {
    expect(minutesLabel(45)).toBe("45 min");
    expect(minutesLabel(60)).toBe("1 h");
    expect(minutesLabel(150)).toBe("2 h 30 min");
  });
});

describe("dates", () => {
  it("treats ISO dates as calendar dates, not instants", () => {
    expect(dateLabel("2026-09-26")).toBe("Sat 26 Sep");
    expect(dateLabel("2026-09-26", true)).toBe("Saturday, 26 Sep");
  });

  it("collapses a range of one day", () => {
    expect(dateRangeLabel("2026-09-26")).toBe("Saturday, 26 Sep");
    expect(dateRangeLabel("2026-09-26", "2026-09-28")).toBe("Sat 26 Sep – Mon 28 Sep");
  });

  it("adds days across month ends", () => {
    expect(addDays("2026-09-30", 1)).toBe("2026-10-01");
    expect(addDays("2026-12-31", 2)).toBe("2027-01-02");
  });

  it("says today and tomorrow relative to a given day", () => {
    expect(relativeDay("2026-09-22", "2026-09-22")).toBe("Today");
    expect(relativeDay("2026-09-23", "2026-09-22")).toBe("Tomorrow");
    expect(relativeDay("2026-09-25", "2026-09-22")).toBeNull();
  });
});

describe("misc", () => {
  it("pluralises", () => {
    expect(plural(1, "stop")).toBe("1 stop");
    expect(plural(3, "person", "people")).toBe("3 people");
  });

  it("describes distance from the centre", () => {
    expect(distanceLabel(0.4)).toBe("400 m from the centre");
    expect(distanceLabel(2.74)).toBe("2.7 km from the centre");
    expect(distanceLabel(47.3)).toBe("47 km from the centre");
  });
});
