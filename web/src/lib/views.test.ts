import { describe, expect, it } from "vitest";
import { VIEWS, offers } from "./views";

describe("offers", () => {
  it("offers trades only to a competition that finds them, and every other view to all", () => {
    expect(offers({ finds_trades: false }, "trades")).toBe(false);
    expect(offers({ finds_trades: true }, "trades")).toBe(true);

    for (const view of VIEWS.filter((v) => v !== "trades")) {
      expect(offers({ finds_trades: false }, view)).toBe(true);
    }
  });
});
