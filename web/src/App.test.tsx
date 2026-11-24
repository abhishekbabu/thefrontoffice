import { act } from "react";
import { useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "@/App";
import { keys } from "@/lib/queries";
import { offlineClient, render, settle } from "@/test/render";
import { competitionOf, leagueOf } from "@/test/leagues";

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

/** Where the app has put the address, for a test to read. */
function Address() {
  const { pathname, search } = useLocation();

  return <output data-testid="address">{pathname + search}</output>;
}

describe("the address", () => {
  it.each([
    ["/nba-yahoo/478.l.1/matchup?week=5&day=2026-11-16", "/nba-yahoo/478.l.1?week=5&day=2026-11-16"],
    ["/nba-yahoo/478.l.1/?week=5", "/nba-yahoo/478.l.1?week=5"],
  ])("keeps its query when %s is settled to the page's own address", async (from, settled) => {
    const client = offlineClient();

    client.setQueryData(keys.competitions, [competitionOf({ key: "nba-yahoo", sport: "basketball" })]);

    client.setQueryData(keys.leagues("nba-yahoo"), [leagueOf("478.l.1")]);

    client.setQueryData(keys.capabilities, { ai: false });

    const { container } = await render(
      <>
        <App />
        <Address />
      </>,
      client,
      from,
    );

    await settle();

    expect(container.querySelector("[data-testid=address]")!.textContent).toBe(settled);
  });
});
