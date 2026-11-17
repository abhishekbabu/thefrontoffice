import { describe, expect, it } from "vitest";
import type { Match } from "@/lib/api";
import { Games } from "@/panels/Fixtures";
import { kickoff } from "@/lib/format";
import { render } from "@/test/render";

const game = (extra: Partial<Match> = {}): Match => ({
  label: "Sun 15 Nov",
  home: "BUF",
  away: "MIA",
  detail: "",
  tone: "neutral",
  home_score: null,
  away_score: null,
  kickoff: null,
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

  it("shows the start time where there is one, in the viewer's zone, and the day otherwise", async () => {
    const iso = "2026-11-22T18:00:00Z";
    const { container } = await render(<Games rows={[game({ kickoff: iso })]} />);
    expect(container.textContent).toContain(kickoff(iso));
    expect(kickoff(iso)).toContain(new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }));
  });
});
