import { afterEach, describe, expect, it } from "vitest";
import { MODE_STORAGE_KEY, PALETTE_STORAGE_KEY } from "@/themes/registry";
import { prePaintScript } from "@/themes/prepaint";

/** Run the script exactly as the page's head will: as source text, on its own. */
function paint(stored: Record<string, string>) {
  localStorage.clear();
  for (const [key, value] of Object.entries(stored)) localStorage.setItem(key, value);
  new Function(prePaintScript())();
  return document.documentElement;
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
  document.documentElement.removeAttribute("data-theme");
});

describe("the pre-paint script", () => {
  it("applies the stored mode and palette under the keys the app writes them to", () => {
    const html = paint({ [MODE_STORAGE_KEY]: "dark", [PALETTE_STORAGE_KEY]: "nord" });

    expect(html.classList.contains("dark")).toBe(true);
    expect(html.getAttribute("data-theme")).toBe("nord");
  });

  it("ignores a stored palette the registry does not know", () => {
    expect(paint({ [PALETTE_STORAGE_KEY]: "catppuccin" }).hasAttribute("data-theme")).toBe(false);
  });

  it("stamps nothing for the default palette, which has no block to select", () => {
    expect(paint({ [PALETTE_STORAGE_KEY]: "vercel" }).hasAttribute("data-theme")).toBe(false);
  });

  it("stays light on a stored light mode", () => {
    expect(paint({ [MODE_STORAGE_KEY]: "light" }).classList.contains("dark")).toBe(false);
  });
});
