import { describe, expect, it } from "vitest";
import type { PlayerCard } from "@/lib/api";
import { RosterTable } from "@/components/league/roster-table";
import { render } from "@/test/render";

const card = (id: string, without: string, notes: Record<string, string> = {}): PlayerCard => ({
  player_id: id,
  columns: { Player: id, Without: without },
  values: {},
  ruled_out: false,
  notes,
  roles: { Player: "player" },
});

describe("RosterTable", () => {
  it("says what a column measures on its heading", async () => {
    const hints = { Without: "Points a game with a teammate out" };
    const { container } = await render(
      <RosterTable players={[card("Mayer", "—")]} empty={{ title: "Nobody" }} sort={null} onSort={() => {}} hints={hints} />,
    );

    const heading = [...container.querySelectorAll("th")].find((th) => th.textContent?.includes("Without"))!;
    expect(heading.querySelector("button")!.getAttribute("aria-label")).toContain(hints.Without);
  });

  it("gives an abbreviated cell its full reading, reachable by keyboard, and leaves the rest plain", async () => {
    const note = "Without Brock Bowers (TE, Q): 6.10/game in 3 games · 8.60 with";
    const { container } = await render(
      <RosterTable
        players={[card("Mayer", "Bowers Q", { Without: note }), card("Kelce", "—")]}
        empty={{ title: "Nobody" }}
        sort={null}
        onSort={() => {}}
      />,
    );

    const noted = container.querySelectorAll<HTMLElement>("[tabindex='0'][aria-label]");
    expect([...noted].map((el) => el.getAttribute("aria-label"))).toEqual([`Bowers Q: ${note}`]);
    expect(container.textContent).toContain("—");
  });

  it("gives a status badge its fuller reading, and leaves one without a note a plain badge", async () => {
    const status = (id: string, value: string, notes: Record<string, string> = {}): PlayerCard => ({
      ...card(id, "—", notes),
      columns: { Player: id, Status: value },
      roles: { Player: "player", Status: "status" },
    });
    const { container } = await render(
      <RosterTable
        players={[status("Curry", "O", { Status: "back ~22 Nov" }), status("Butler", "GTD")]}
        empty={{ title: "Nobody" }}
        sort={null}
        onSort={() => {}}
      />,
    );

    const noted = container.querySelectorAll<HTMLElement>("[tabindex='0'][aria-label]");
    expect([...noted].map((el) => el.getAttribute("aria-label"))).toEqual(["O: back ~22 Nov"]);
    expect(container.textContent).toContain("GTD");
  });
});
