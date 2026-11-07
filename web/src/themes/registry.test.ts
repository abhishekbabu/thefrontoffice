import { describe, expect, it } from "vitest";
import { DEFAULT_PALETTE, PALETTES, applyPalette, isPaletteId } from "@/themes/registry";
import themes from "@/themes/themes.css?raw";

describe("palette registry", () => {
  it("registers the default", () => {
    expect(PALETTES.map((p) => p.id)).toContain(DEFAULT_PALETTE);
  });

  it("gives every palette a distinct id", () => {
    expect(new Set(PALETTES.map((p) => p.id)).size).toBe(PALETTES.length);
  });

  it("gives every palette but the default a block in themes.css to select", () => {
    // A registered palette with no block is a picker entry that changes nothing.
    // The default needs none: it lives in @theme.
    const selectors = [...themes.matchAll(/^html\[data-theme="([^"]+)"\] {/gm)].map((match) => match[1]);
    expect(new Set(selectors)).toEqual(new Set(PALETTES.map((p) => p.id).filter((id) => id !== DEFAULT_PALETTE)));
  });

  it("rejects an unknown id, so a stale stored value falls back", () => {
    expect(isPaletteId("catppuccin")).toBe(false);
    expect(isPaletteId(null)).toBe(false);
    expect(isPaletteId("floodlight")).toBe(true);
  });

  it("clears the attribute for the default rather than stamping it", () => {
    // The default lives in @theme, so an attribute for it would select a block
    // that does not exist and quietly do nothing.
    applyPalette("floodlight");
    expect(document.documentElement.getAttribute("data-theme")).toBe("floodlight");
    applyPalette(DEFAULT_PALETTE);
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });
});
