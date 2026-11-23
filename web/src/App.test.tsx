import { act } from "react";
import { describe, expect, it } from "vitest";
import App from "@/App";
import { keys } from "@/lib/queries";
import { offlineClient, render } from "@/test/render";

/** The shell with nothing connected: the rail is all there is to look at. */
async function shell() {
  const client = offlineClient();

  client.setQueryData(keys.competitions, []);

  client.setQueryData(keys.capabilities, { ai: false });

  return render(<App />, client);
}

const menu = (container: HTMLElement) => container.querySelector<HTMLButtonElement>('button[aria-controls="rail"]')!;

describe("App", () => {
  it("opens the phone menu, and closes it once a link in it is followed", async () => {
    const { container } = await shell();

    expect(menu(container).getAttribute("aria-expanded")).toBe("false");

    await act(async () => menu(container).click());

    expect(menu(container).getAttribute("aria-expanded")).toBe("true");
    expect(menu(container).getAttribute("aria-label")).toBe("Close menu");

    const settings = [...container.querySelectorAll<HTMLAnchorElement>("#rail a")].find(
      (a) => a.textContent === "Settings",
    )!;

    await act(async () => settings.click());

    expect(menu(container).getAttribute("aria-expanded")).toBe("false");
  });

  it("closes the phone menu from its own button", async () => {
    const { container } = await shell();

    await act(async () => menu(container).click());

    await act(async () => menu(container).click());

    expect(menu(container).getAttribute("aria-expanded")).toBe("false");
  });
});
