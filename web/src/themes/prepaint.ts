/**
 * The theme, put on <html> before the first paint.
 *
 * The app's own code arrives as a module, which runs after the page has
 * painted — so without this a dark-mode reader sees a light frame first. It
 * runs as an inline script that `vite.config.ts` writes into index.html from
 * this module, so the keys it reads, the palettes it accepts and the default
 * it falls back to are the registry's own rather than a copy in the HTML.
 *
 * Imports are relative: the Vite config loads this file, and the `@/` alias
 * is the app's, not the config's.
 */
import { DEFAULT_PALETTE, MODE_STORAGE_KEY, PALETTES, PALETTE_STORAGE_KEY } from "./registry";

type Stored = { modeKey: string; paletteKey: string; palettes: readonly string[]; fallback: string };

/**
 * Apply what is stored: a stored mode wins over the OS, and a palette the
 * registry does not know — renamed, removed, or written by hand — is ignored
 * rather than stamped on a page with no block for it.
 *
 * Written into the page as its source text, so it closes over nothing and
 * imports nothing: everything it needs arrives as `stored`.
 */
export function prePaint(stored: Stored): void {
  try {
    const mode = localStorage.getItem(stored.modeKey);
    const dark = mode === "dark" || mode === "light" ? mode === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.classList.toggle("dark", dark);
    const palette = localStorage.getItem(stored.paletteKey);
    if (palette && palette !== stored.fallback && stored.palettes.includes(palette)) {
      document.documentElement.setAttribute("data-theme", palette);
    }
  } catch {
    // Storage blocked: the light default stands.
  }
}

/** The script that goes in the page's head: `prePaint`, called with the registry's values. */
export function prePaintScript(): string {
  const stored: Stored = {
    modeKey: MODE_STORAGE_KEY,
    paletteKey: PALETTE_STORAGE_KEY,
    palettes: PALETTES.map((p) => p.id),
    fallback: DEFAULT_PALETTE,
  };
  return `(${prePaint.toString()})(${JSON.stringify(stored)});`;
}
