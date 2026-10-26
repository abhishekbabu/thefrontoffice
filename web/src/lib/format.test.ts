import { describe, expect, it } from "vitest";
import { percent, percentPoints, signed } from "@/lib/format";

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
});
