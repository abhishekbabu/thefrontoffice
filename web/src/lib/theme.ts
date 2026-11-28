/**
 * Light or dark, and which palette: read from what the pre-paint script
 * (`themes/prepaint.ts`) already put on <html>, and changed by Commands, since
 * a change repaints the page and is kept in the browser.
 *
 * Storage throws rather than returning null in some contexts — a private
 * window, or a browser set to block site data. A theme preference is a
 * convenience, so failing to read or write one must never take the page down.
 */
import { Command } from "@effect/ui";
import { HtmlSubscription } from "@effect/ui/html";
import { Effect, Schema } from "effect";
import { DEFAULT_PALETTE, MODE_STORAGE_KEY, PALETTE_STORAGE_KEY, isPaletteId, type PaletteId } from "@/themes/registry";
import { applyPalette, repaint } from "@/themes/paint";

export const Mode = Schema.Literals(["light", "dark"]);

export type Mode = typeof Mode.Type;

function safeRead(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeWrite(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // The preference simply will not persist.
    return;
  }
}

/** The mode and palette the page is painted in, and whether its mode is the system's. */
type Theme = { mode: Mode; palette: PaletteId; followsSystem: boolean };

/** The theme the page is painted in now, as the app starts. */
export function currentTheme(): Theme {
  const stored = safeRead(PALETTE_STORAGE_KEY);
  const mode: Mode = document.documentElement.classList.contains("dark") ? "dark" : "light";

  return {
    mode,
    palette: isPaletteId(stored) ? stored : DEFAULT_PALETTE,
    // Follow the OS only while the user has expressed no preference of their own.
    followsSystem: !safeRead(MODE_STORAGE_KEY),
  };
}

/**
 * Paint the page `mode`. A choice the user made (`chosen`) is kept for the
 * next visit, and crossfades in; one the system made is followed at once and
 * kept nowhere, so the page goes on following it.
 */
export const PaintMode = Command.make("PaintMode", { args: { mode: Mode, chosen: Schema.Boolean } }, ({ mode, chosen }) =>
  Effect.sync(() => {
    const apply = () => document.documentElement.classList.toggle("dark", mode === "dark");

    if (!chosen) return void apply();

    repaint(apply);

    safeWrite(MODE_STORAGE_KEY, mode);
  }),
);

/** Paint the page in `palette`, and keep it. */
export const PaintPalette = Command.make("PaintPalette", { args: { palette: Schema.String } }, ({ palette }) =>
  Effect.sync(() => {
    if (!isPaletteId(palette)) return;

    repaint(() => applyPalette(palette));

    safeWrite(PALETTE_STORAGE_KEY, palette);
  }),
);

/** The system's own light or dark, as it changes: what a page that follows the OS repaints to. */
export function systemMode<M>(toMessage: (mode: Mode) => M) {
  return HtmlSubscription.onMediaQuery("(prefers-color-scheme: dark)", (dark) => toMessage(dark ? "dark" : "light"));
}
