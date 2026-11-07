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

export type PaletteMeta = (typeof PALETTES)[number];
export type PaletteId = PaletteMeta["id"];

const VALID = new Set<string>(PALETTES.map((p) => p.id));

export function isPaletteId(value: string | null): value is PaletteId {
  return value != null && VALID.has(value);
}

/** Apply a palette by setting the attribute the CSS keys off. */
export function applyPalette(palette: PaletteId): void {
  if (palette === DEFAULT_PALETTE) {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", palette);
  }
}

/**
 * Repaint under a whole-page crossfade, where the browser can do one.
 *
 * Easing the tokens themselves is what the suppression below exists to stop:
 * forty of them interpolate independently and the swap reads as a smear. A
 * view transition has no such problem — it crossfades a snapshot of the old
 * frame into the new one, so the page changes as a single image and the
 * tokens still swap instantly underneath.
 *
 * Falls back to the instant swap where the API is missing, and takes it
 * deliberately when the viewer has asked for less motion.
 */
export function repaint(apply: () => void): void {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (still || typeof doc.startViewTransition !== "function") {
    suppressThemeTransitions();
    apply();
    return;
  }
  doc.startViewTransition(apply);
}

/**
 * Make the next palette or mode change paint in one frame.
 *
 * The fallback for browsers with no view transitions. Around forty tokens
 * change at once; left to their own easing they interpolate independently and
 * the swap reads as a smear. This disables easing, forces a reflow so the
 * suppression lands before the repaint, then lifts it after the paint. Callers
 * must change the token *synchronously* after calling this, not in an effect,
 * or the class will have lifted before the change lands.
 */
export function suppressThemeTransitions(): void {
  const root = document.documentElement;
  root.classList.add("theme-switching");
  void root.offsetWidth; // force reflow
  requestAnimationFrame(() => {
    requestAnimationFrame(() => root.classList.remove("theme-switching"));
  });
}

/**
 * Warn in development if a registered palette has no CSS block.
 *
 * Such a palette silently renders as the default — the picker offers it, the
 * click does nothing, and neither the typechecker nor the build notices. Read
 * back the raw custom property, which is empty for a missing block.
 */
export function assertPalettesResolve(): void {
  if (!import.meta.env.DEV) return;
  const root = document.documentElement;
  const original = root.getAttribute("data-theme");
  for (const { id } of PALETTES) {
    if (id === DEFAULT_PALETTE) continue;
    root.setAttribute("data-theme", id);
    if (!getComputedStyle(root).getPropertyValue("--color-background").trim()) {
      console.warn(`Palette "${id}" is registered but has no themes.css block; it renders as the default.`);
    }
  }
  if (original) root.setAttribute("data-theme", original);
  else root.removeAttribute("data-theme");
}
