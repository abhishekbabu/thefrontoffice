import { describe, expect, it } from "vitest";
import type { Capabilities, Competition, League, PlayerDetail } from "@/lib/api";
import { keys } from "@/lib/queries";
import { usePlayerDrawer } from "@/components/ui/player";
import { offlineClient, press, render, settle } from "@/test/render";
import { playerDetail } from "@/test/players";

const NFL = { key: "nfl-sleeper" } as Competition;
const LEAGUE = { league_id: "900" } as League;
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
  const { openPlayer, drawer } = usePlayerDrawer(NFL, LEAGUE);
  return (
    <>
      <button type="button" onClick={() => openPlayer(ALLEN.player_id)}>
        Josh Allen
      </button>
      {drawer}
    </>
  );
}

describe("the player drawer", () => {
  it("opens as a modal dialog named for the player, and Escape closes it", async () => {
    const client = offlineClient();
    client.setQueryData<Capabilities>(keys.capabilities, { ai: false, limits: { judged: 10 } });
    client.setQueryData(keys.player(NFL.key, LEAGUE.league_id, ALLEN.player_id), ALLEN);
    const { container } = await render(<Roster />, client);

    container.querySelector("button")!.click();
    await settle();
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');

    expect([dialog?.getAttribute("aria-modal"), dialog?.getAttribute("aria-label")]).toEqual(["true", "Josh Allen"]);
    expect(dialog?.contains(document.activeElement)).toBe(true);

    await press(dialog!, "Escape");
    await settle(400);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

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
    const client = offlineClient();
    client.setQueryData<Capabilities>(keys.capabilities, { ai: false, limits: { judged: 10 } });
    client.setQueryData(keys.player(NFL.key, LEAGUE.league_id, ALLEN.player_id), tabbed);
    const { container } = await render(<Roster />, client);

    container.querySelector("button")!.click();
    await settle();
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!;
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
    const client = offlineClient();
    client.setQueryData<Capabilities>(keys.capabilities, { ai: false, limits: { judged: 10 } });
    client.setQueryData(keys.player(NFL.key, LEAGUE.league_id, ALLEN.player_id), lazy);
    client.setQueryData(keys.playerTab(NFL.key, LEAGUE.league_id, ALLEN.player_id, "Seasons"), seasons);
    client.setQueryData(keys.playerTab(NFL.key, LEAGUE.league_id, ALLEN.player_id, "News"), playerDetail({ ...ALLEN }));
    const { container } = await render(<Roster />, client);

    container.querySelector("button")!.click();
    await settle();
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!;
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
    const client = offlineClient();
    client.setQueryData<Capabilities>(keys.capabilities, { ai: false, limits: { judged: 10 } });
    client.setQueryData(keys.player(NFL.key, LEAGUE.league_id, ALLEN.player_id), traded);
    const { container } = await render(<Roster />, client);

    container.querySelector("button")!.click();
    await settle();
    const drawer = document.querySelector<HTMLElement>('[role="dialog"]')!;
    drawer.querySelectorAll<HTMLButtonElement>('[role="tab"]')[1]!.click();
    await settle();
    const row = [...drawer.querySelectorAll<HTMLElement>("[role=button]")].find((el) => el.textContent?.includes("Trade"))!;
    row.click();
    await settle();

    const move = document.querySelector("[aria-label='Trade by Rival ↔ Me']");
    expect(move?.textContent).toContain("To Rival");
  });
});
