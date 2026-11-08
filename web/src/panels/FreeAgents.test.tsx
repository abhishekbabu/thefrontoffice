import { describe, expect, it } from "vitest";
import type { PlayerCall } from "@/lib/api";
import { withCalls } from "@/panels/FreeAgents";

const call = (player_id: string, decision: PlayerCall["decision"], stale = false): PlayerCall => ({
  player_id,
  decision,
  drop: "",
  reason: "",
  judged_at: null,
  stale,
});

describe("the calls a judging makes", () => {
  it("take the place of the kept ones on the same players and leave the rest", () => {
    const kept = [call("a", "PASS", true), call("b", "WATCH")];

    const merged = withCalls(kept, [call("a", "ADD"), call("c", "PASS")]);

    expect(Object.fromEntries(merged.map((c) => [c.player_id, [c.decision, c.stale]]))).toEqual({
      a: ["ADD", false],
      b: ["WATCH", false],
      c: ["PASS", false],
    });
  });
});
