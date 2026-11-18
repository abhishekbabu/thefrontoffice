import { describe, expect, it } from "vitest";
import type { PlayerCard } from "@/lib/api";
import { RosterTable } from "@/components/ui/roster-table";
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
});
