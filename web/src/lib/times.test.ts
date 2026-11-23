import { describe, expect, it } from "vitest";
import { moment, startsAt } from "@/lib/times";

describe("a recent moment", () => {
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
