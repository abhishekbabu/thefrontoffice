import { describe, expect, it } from "vitest";
import type { TradeIdea } from "@/lib/api";
import { theirCase } from "@/panels/Team";

const idea = (their_playoffs: number, their_points: number): TradeIdea => ({
  team_id: "2",
  team: "rival",
  giving: ["A"],
  receiving: ["B"],
  playoffs: 0.9,
  playoffs_change: 0.01,
  their_playoffs_change: 0,
  points: 1,
  their_points,
  playoff_points: 3,
  their_playoffs,
  pickup: "",
  form: [],
});

describe("why the other manager might take a trade", () => {
  it("is what it is worth, once he is out of the race", () => {
    expect(theirCase(idea(0.01, -2.6))).toContain("out of the race");
  });

  it("is his starters, while he is still chasing a place", () => {
    expect(theirCase(idea(0.4, 1.4))).toContain("+1.4");
  });
});
