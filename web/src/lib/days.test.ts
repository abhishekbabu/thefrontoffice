import { describe, expect, it } from "vitest";
import { addDays, dayLabel, dayNumber, isDay } from "@/lib/days";

describe("calendar days", () => {
  it("steps across a month's end either way", () => {
    expect(addDays("2026-11-30", 1)).toBe("2026-12-01");
    expect(addDays("2026-12-01", -1)).toBe("2026-11-30");
  });

  it("orders days by their number", () => {
    expect(dayNumber("2026-11-25") - dayNumber("2026-11-23")).toBe(2);
  });

  it("says a day as its weekday, date and month, whatever the viewer's zone", () => {
    expect(dayLabel("2026-11-24")).toBe("Tue 24 Nov");
  });

  it("takes only a day written the way the server writes one", () => {
    expect(isDay("2026-11-24")).toBe(true);
    expect(isDay("24 Nov")).toBe(false);
    expect(isDay("2026-13-40")).toBe(false);
    expect(isDay(null)).toBe(false);
  });
});
