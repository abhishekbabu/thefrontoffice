import { describe, expect, it } from "vitest";
import type { Match } from "@/lib/api";
import { Games } from "@/panels/Fixtures";
import { render } from "@/test/render";

const game = (extra: Partial<Match> = {}): Match => ({
  label: "Sun 15 Nov",
  home: "BUF",
  away: "MIA",
  detail: "",
  tone: "neutral",
  home_score: null,
  away_score: null,
  ...extra,
});

describe("Games", () => {
  it("puts each side's score beside it once the game has kicked off", async () => {
    const { container } = await render(<Games rows={[game({ home_score: 27, away_score: 20, detail: "Final" })]} />);
    expect(container.textContent).toContain("MIA 20 at BUF 27");
  });

  it("shows no score for a game yet to start", async () => {
    const { container } = await render(<Games rows={[game()]} />);
    expect(container.textContent).toContain("MIA at BUF");
    expect(container.textContent).not.toMatch(/\d+ at/);
  });
});
