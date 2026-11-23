import { describe, expect, it } from "vitest";
import { DEFAULT_PALETTE } from "@/themes/registry";
import { applyPalette } from "@/themes/paint";

describe("applying a palette", () => {
  it("clears the attribute for the default rather than stamping it", () => {
    // The default lives in @theme, so an attribute for it would select a block
    // that does not exist and quietly do nothing.
    applyPalette("floodlight");

    expect(document.documentElement.getAttribute("data-theme")).toBe("floodlight");

    applyPalette(DEFAULT_PALETTE);

    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });
});
