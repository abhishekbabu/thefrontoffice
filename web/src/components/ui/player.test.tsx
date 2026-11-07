import { describe, expect, it } from "vitest";
import type { Capabilities, Competition, League, PlayerDetail } from "@/lib/api";
import { keys } from "@/lib/queries";
import { usePlayerDrawer } from "@/components/ui/player";
import { offlineClient, press, render, settle } from "@/test/render";

const NFL = { key: "nfl-sleeper" } as Competition;
const LEAGUE = { league_id: "900" } as League;
const ALLEN: PlayerDetail = {
  player_id: "17",
  name: "Josh Allen",
  position: "QB",
  team: "BUF",
  team_name: "Buffalo Bills",
  team_logo_url: "",
  headline: "24.1",
  headline_label: "proj pts",
  note: "",
  url: "",
  image_url: "",
  tone: "neutral",
  groups: [],
  tables: [],
};

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
});
