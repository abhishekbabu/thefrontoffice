import { describe, expect, it } from "vitest";
import type { ActivityRow } from "@/lib/api";
import { sections } from "@/components/ui/move";

describe("sections", () => {
  it("reads one manager's move as what he added and what he let go", () => {
    const claim: ActivityRow = {
      when: "11 Nov",
      who: "Me",
      what: "Waiver",
      detail: "",
      is_mine: true,
      bid: "$14",
      moves: [
        { player_id: "wr9", player: "Waiver WR", position: "WR", team: "NYJ", change: "added", manager: "Me" },
        { player_id: "rb1", player: "Good RB", position: "RB", team: "BUF", change: "dropped", manager: "Me" },
      ],
    };

    expect(sections(claim).map((s) => [s.title, s.moves.map((m) => m.player)])).toEqual([
      ["Added", ["Waiver WR"]],
      ["Dropped", ["Good RB"]],
    ]);
  });
});
