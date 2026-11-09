import { describe, expect, it } from "vitest";
import type { Spot } from "@/lib/api";
import { LineupCard } from "@/components/ui/lineup";
import { render } from "@/test/render";

function spot(player: string, mark = ""): Spot {
  return { player_id: player, slot: "", player, mark, detail: "MID · ARS vs LIV (2)", value: "6.0 xPts", tone: "neutral", scoring: null, scored: "", projection: "" };
}

describe("LineupCard", () => {
  it("shows an armband as a chip beside the name, not inside it", async () => {
    const { container } = await render(
      <LineupCard title="You" lineup={[spot("Haaland", "C"), spot("Isak", "VC"), spot("Rice")]} bench={[]} swaps={[]} />,
    );

    const names = [...container.querySelectorAll("span.truncate")].map((name) => name.textContent);
    expect(names).toEqual(["Haaland", "Isak", "Rice"]);
    expect(container.textContent).toContain("HaalandC");
    expect(container.textContent).toContain("IsakVC");
    expect(container.textContent).not.toContain("RiceC");
  });
});
