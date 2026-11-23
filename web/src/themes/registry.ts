/**
 * The palette registry — the single source of truth the picker renders from and
 * the hook validates against.
 *
 * A palette is the *color* dimension. Light versus dark is a separate,
 * orthogonal dimension (see `lib/useTheme`) that selects each token's
 * `light-dark()` arm. Ten palettes and two modes cost ten CSS blocks, not
 * twenty: no component ever branches on either.
 */

export const PALETTE_STORAGE_KEY = "tfo:palette";

/** Where light or dark is kept: written by `useTheme`, read before first paint by `prepaint.ts`. */
export const MODE_STORAGE_KEY = "tfo:mode";

/** Defined in `index.css` under `@theme`, so it has no `themes.css` block. */
export const DEFAULT_PALETTE = "vercel";

// `as const` so PaletteId is derived from the array rather than maintained
// beside it — adding an entry updates the type with nothing else to touch.
export const PALETTES = [
  { id: "vercel", label: "Vercel", hint: "Default · monochrome, blue focus", swatch: "#0070f3" },
  { id: "floodlight", label: "Floodlight", hint: "Amber on cool near-black", swatch: "#f5b700" },
  { id: "nord", label: "Nord", hint: "Arctic blue-grey", swatch: "#88c0d0" },
  { id: "solarized", label: "Solarized", hint: "Precision light / dark", swatch: "#268bd2" },
  { id: "ember", label: "Ember", hint: "Warm orange", swatch: "#fb923c" },
] as const;

type PaletteMeta = (typeof PALETTES)[number];

export type PaletteId = PaletteMeta["id"];

const VALID = new Set<string>(PALETTES.map((p) => p.id));

export function isPaletteId(value: string | null): value is PaletteId {
  return value != null && VALID.has(value);
}
