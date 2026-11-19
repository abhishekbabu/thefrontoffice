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
  yours: [],
  theirs: [],
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

  it("shows the start time in the viewer's zone", async () => {
    const iso = "2026-11-22T18:00:00Z";
    const { container } = await render(<Games rows={[game({ kickoff: iso })]} />);
    expect(container.textContent).toContain(new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }));
  });

  it("says each kickoff once, over the games that share it", async () => {
    const early = "2026-11-22T18:00:00Z";
    const late = "2026-11-22T21:25:00Z";
    const rows = [
      game({ kickoff: early }),
      game({ home: "DAL", away: "NYG", kickoff: early }),
      game({ home: "SF", away: "SEA", kickoff: late }),
    ];
    const { container } = await render(<Games rows={rows} />);
    const text = container.textContent ?? "";

    expect(text.split(kickoff(early))).toHaveLength(2);
    expect(text.split(kickoff(late))).toHaveLength(2);
    expect(text.indexOf(kickoff(late))).toBeGreaterThan(text.indexOf("NYG at DAL"));
  });

  it("names whose players are in a game, yours apart from your opponent's", async () => {
    const both = game({
      yours: [{ player_id: "1", name: "Josh Allen", detail: "QB · starting" }],
      theirs: [{ player_id: "2", name: "Tua Tagovailoa", detail: "QB · starting" }],
    });
    const { container } = await render(<Games rows={[both]} />);

    expect(container.textContent).toContain("YouJosh Allen");
    expect(container.textContent).toContain("OppTua Tagovailoa");
  });

  it("lists the week's byes on one line, and none where every club plays", async () => {
    const withByes = await render(<Games rows={[game()]} byes={["KC", "LAR"]} />);
    expect(withByes.container.textContent).toContain("ByesKC, LAR");

    const without = await render(<Games rows={[game()]} />);
    expect(without.container.textContent).not.toContain("Byes");
  });

  it("says when the week's schedule is not final, and nothing for a week that is", async () => {
    const pending = await render(<Games rows={[game()]} note="Schedule not final: no games yet 4-11 Dec." />);
    expect(pending.container.textContent).toContain("4-11 Dec");

    const settled = await render(<Games rows={[game()]} />);
    expect(settled.container.textContent).not.toContain("Schedule");
  });

  it("opens a game only where somebody's players are in it", async () => {
    const opened: Match[] = [];
    const mine = game({ home: "DAL", yours: [{ player_id: "1", name: "Lamb", detail: "WR · starting" }] });
    const { container } = await render(<Games rows={[mine, game()]} onOpen={(g) => opened.push(g)} />);

    const rows = [...container.querySelectorAll<HTMLElement>("[role=button]")];
    expect(rows).toHaveLength(1);
    rows[0]!.click();
    expect(opened.map((g) => g.home)).toEqual(["DAL"]);
  });
});
