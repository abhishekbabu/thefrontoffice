/**
 * Putting a palette on the page: setting it, and repainting so a change reads
 * as one swap rather than forty tokens easing at different speeds.
 */
import { DEFAULT_PALETTE, PALETTES, type PaletteId } from "@/themes/registry";

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
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (still || !("startViewTransition" in document)) {
    suppressThemeTransitions();

    apply();

    return;
  }

  document.startViewTransition(apply);
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
