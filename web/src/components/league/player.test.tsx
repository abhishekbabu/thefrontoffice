import { act } from "react";
import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import type { PlayerCard, PlayerDetail } from "@/lib/types";
import { server } from "@/test/server";
import { keys } from "@/lib/queries";
import { useDrawers } from "@/components/league/drawers";
import { drawerClient, render, settle } from "@/test/render";
import { playerDetail } from "@/test/players";
import { competitionOf, leagueOf } from "@/test/leagues";

const NFL = competitionOf({ key: "nfl-sleeper" });
const LEAGUE = leagueOf("900");

const ALLEN: PlayerDetail = playerDetail({
  player_id: "17",
  name: "Josh Allen",
  position: "QB",
  team: "BUF",
  team_name: "Buffalo Bills",
  headline: "24.1",
  headline_label: "proj pts",
});

function Roster() {
  const { openPlayer, drawer } = useDrawers(NFL, LEAGUE);

  return (
    <>
      <button type="button" onClick={() => openPlayer(ALLEN.player_id)}>
        Josh Allen
      </button>
      {drawer}
    </>
  );
}

/** Him as a row of your roster. */
const ALLEN_CARD: PlayerCard = {
  player_id: ALLEN.player_id,
  columns: { Player: ALLEN.name },
  values: {},
  ruled_out: false,
  notes: {},
  roles: { Player: "player" },
};

/** Open his drawer on `detail`, with each of `tabs` answering its own read, and `roster` as yours. */
async function opened(detail: PlayerDetail, tabs: Record<string, PlayerDetail> = {}, roster: PlayerCard[] = []) {
  const client = drawerClient();

  client.setQueryData([...keys.roster(NFL.key, LEAGUE.league_id), null], roster);

  client.setQueryData(keys.untouchables(NFL.key, LEAGUE.league_id), { player_ids: [] });

  client.setQueryData(keys.player(NFL.key, LEAGUE.league_id, ALLEN.player_id), detail);

  for (const [tab, read] of Object.entries(tabs)) {
    client.setQueryData(keys.playerTab(NFL.key, LEAGUE.league_id, ALLEN.player_id, tab), read);
  }

  const { container } = await render(<Roster />, client);

  container.querySelector("button")!.click();

  await settle();

  return document.querySelector<HTMLElement>('[role="dialog"]')!;
}

/** The facts under his name, each label to its value: the first list in the drawer, its header's. */
function facts(dialog: HTMLElement): Record<string, string> {
  const terms = dialog.querySelector("dl");

  if (!terms) return {};

  return Object.fromEntries(
    [...terms.querySelectorAll("dt")].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent ?? ""]),
  );
}

describe("the player drawer", () => {
  it("shows one tab at a time, offers only tabs with something in them, and names his owner", async () => {
    const tabbed: PlayerDetail = {
      ...ALLEN,
      owner: "Rival",
      tabs: ["This week", "History", "News"],
      groups: [
        { title: "Week 11", tab: "", note: "", stats: [{ label: "Projected", value: "24.1", tone: "neutral", url: "", better: null, hint: "" }] },
        { title: "Moves", tab: "History", note: "", stats: [{ label: "Draft", value: "Round 1", tone: "neutral", url: "", better: null, hint: "" }] },
        { title: "Latest news", tab: "News", note: "", stats: [] },
      ],
    };

    const dialog = await opened(tabbed);

    const tabs = [...dialog.querySelectorAll('[role="tab"]')].map((t) => t.textContent);

    expect(tabs).toEqual(["This week", "History"]);
    expect(dialog.textContent).toContain("Rival");
    expect(dialog.textContent).toContain("Projected");
    expect(dialog.textContent).not.toContain("Round 1");

    dialog.querySelectorAll<HTMLButtonElement>('[role="tab"]')[1]!.click();

    await settle();

    expect(dialog.textContent).toContain("Round 1");
    expect(dialog.textContent).not.toContain("Projected");
  });

  it("sets each fact under his name as its label over its value, and his status in words", async () => {
    const dialog = await opened({ ...ALLEN, rank: "QB3", owner: "Rival", note: "Questionable", tone: "warning" });

    expect(facts(dialog)).toEqual({ "proj pts": "24.1", "Pos rank": "QB3", Owner: "Rival" });
    expect(dialog.textContent).toContain("Questionable");
  });

  it("says why there is no figure, and shows only the facts he has", async () => {
    const dialog = await opened({ ...ALLEN, headline: "", headline_label: "Not projected in week 11", owner: "Free agent" });

    expect(facts(dialog)).toEqual({ Owner: "Free agent" });
    expect(dialog.textContent).toContain("Not projected in week 11");
  });

  it("offers a deferred tab before it is read, and shows what its own read holds once opened", async () => {
    const lazy = playerDetail({
      ...ALLEN,
      tabs: ["This week", "Seasons", "News"],
      deferred: ["Seasons", "News"],
      groups: [{ title: "Week 11", tab: "", note: "", stats: [{ label: "Projected", value: "24.1", tone: "neutral", url: "", better: null, hint: "" }] }],
    });

    const seasons = playerDetail({
      ...ALLEN,
      tables: [{ title: "By season", tab: "Seasons", columns: ["2025-26"], rows: [{ label: "PTS", values: ["14.8"], tone: "neutral", better: "higher", best: [] }], absent: "N/A" }],
    });

    const dialog = await opened(lazy, { Seasons: seasons, News: playerDetail({ ...ALLEN }) });

    const tabs = [...dialog.querySelectorAll<HTMLButtonElement>('[role="tab"]')];

    expect(tabs.map((t) => t.textContent)).toEqual(["This week", "Seasons", "News"]);

    tabs[1]!.click();

    await settle();

    expect(dialog.textContent).toContain("2025-26");
    expect(dialog.textContent).not.toContain("Projected");

    tabs[2]!.click();

    await settle();

    expect(dialog.textContent).toContain("No news on record.");
  });

  it("opens a move on his history the way Activity does", async () => {
    const traded = playerDetail({
      ...ALLEN,
      tabs: ["This week", "History"],
      moves_tab: "History",
      groups: [{ title: "Week 11", tab: "", note: "", stats: [{ label: "Projected", value: "24.1", tone: "neutral", url: "", better: null, hint: "" }] }],
      moves: [
        {
          when: "19 Sep",
          who: "Rival ↔ Me",
          what: "Trade",
          detail: "+Josh Allen · +Bad RB",
          is_mine: true,
          bid: "",
          moves: [
            { player_id: "17", player: "Josh Allen", position: "QB", team: "BUF", change: "added", manager: "Me" },
            { player_id: "rb2", player: "Bad RB", position: "RB", team: "MIA", change: "added", manager: "Rival" },
          ],
        },
      ],
    });

    const drawer = await opened(traded);

    drawer.querySelectorAll<HTMLButtonElement>('[role="tab"]')[1]!.click();

    await settle();

    const row = [...drawer.querySelectorAll<HTMLElement>("[role=button]")].find((el) => el.textContent?.includes("Trade"))!;

    row.click();

    await settle();

    const move = document.querySelector("[aria-label='Trade by Rival ↔ Me']");

    expect(move?.textContent).toContain("To Rival");
  });

  it("offers no untouchable mark on a player who is not yours", async () => {
    const dialog = await opened(ALLEN);

    expect(dialog.querySelector('button[aria-label="Mark untouchable"]')).toBeNull();
  });

  it("marks one of yours untouchable on the server, and the lock and its name say so", async () => {
    const sent: unknown[] = [];

    server.use(
      http.post("*/untouchables", async ({ request }) => {
        sent.push(await request.json());

        return HttpResponse.json({ player_ids: [ALLEN.player_id] });
      }),
    );

    const dialog = await opened(ALLEN, {}, [ALLEN_CARD]);

    await act(async () => dialog.querySelector<HTMLButtonElement>('button[aria-label="Mark untouchable"]')!.click());

    await settle();

    expect(sent).toEqual([{ player_id: ALLEN.player_id, untouchable: true }]);

    const marked = dialog.querySelector<HTMLButtonElement>('button[aria-label="Untouchable: clear"]');

    expect(marked?.getAttribute("aria-pressed")).toBe("true");
  });
});
