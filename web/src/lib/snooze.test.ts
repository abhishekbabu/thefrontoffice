import { describe, expect, it } from "vitest";
import { SNOOZES, morningAfter } from "@/lib/snooze";

describe("snoozing", () => {
  const now = new Date(2026, 9, 22, 21, 30); // a Thursday evening, local

  it("puts a morning snooze at 8am on the day it names", () => {
    const tomorrow = morningAfter(now, 1);
    expect([tomorrow.getDate(), tomorrow.getHours(), tomorrow.getMinutes()]).toEqual([23, 8, 0]);
  });

  it("crosses a month end rather than overflowing it", () => {
    const later = morningAfter(new Date(2026, 9, 30, 12), 3);
    expect([later.getMonth(), later.getDate()]).toEqual([10, 2]);
  });

  it("only ever offers times still to come", () => {
    for (const snooze of SNOOZES) expect(snooze.until(now).getTime()).toBeGreaterThan(now.getTime());
  });
});
