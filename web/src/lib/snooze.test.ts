import { describe, expect, it } from "vitest";
import { SNOOZES, morningAfter } from "@/lib/snooze";

describe("snoozing", () => {
  const now = new Date(2026, 9, 22, 21, 30); // a Thursday evening, local

  it("puts a morning snooze at 8am on the day it names", () => {
    const tomorrow = morningAfter(now, 1);
    expect([tomorrow.getDate(), tomorrow.getHours(), tomorrow.getMinutes()]).toEqual([23, 8, 0]);
  });

  it("only ever offers times still to come", () => {
    for (const snooze of SNOOZES) expect(snooze.until(now).getTime()).toBeGreaterThan(now.getTime());
  });
});
