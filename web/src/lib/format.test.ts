import { describe, expect, it } from "vitest";
import { moment, percent, percentPoints, signed, startsAt } from "@/lib/format";

describe("formatting a figure", () => {
  it("signs a change either way, with the minus that lines up with the plus", () => {
    expect([signed(1.63), signed(-0.4), signed(0)]).toEqual(["+1.6", "−0.4", "+0.0"]);
  });

  it("writes a change in a chance as percentage points", () => {
    expect(percentPoints(0.0146)).toBe("+1.5 pts");
  });

  it("writes a chance as a whole percentage", () => {
    expect(percent(0.9108)).toBe("91%");
  });

  it("names the day of a moment only when it was not today", () => {
    const now = new Date(2026, 9, 22, 21, 30);
    expect(moment(new Date(2026, 9, 22, 14, 5).toISOString(), now)).not.toMatch(/[A-Za-z]{3}/);
    expect(moment(new Date(2026, 9, 20, 14, 5).toISOString(), now)).toMatch(/^[A-Za-z]{3}/);
  });
});

describe("when a game starts, on a lineup row", () => {
  const now = new Date(2026, 10, 19, 12, 0);

  it("says today for a game today, and the weekday for one later in the week", () => {
    expect(startsAt(new Date(2026, 10, 19, 17, 15).toISOString(), now)).toMatch(/^today /);
    expect(startsAt(new Date(2026, 10, 22, 13, 0).toISOString(), now)).toMatch(/^Sun /);
  });

  it("dates a game more than a week off, where the weekday alone would not place it", () => {
    expect(startsAt(new Date(2026, 11, 6, 15, 0).toISOString(), now)).toMatch(/^Sun.*6/);
    expect(startsAt(new Date(2026, 10, 22, 13, 0).toISOString(), now)).not.toMatch(/22/);
  });
});
