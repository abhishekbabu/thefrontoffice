import { describe, expect, it } from "vitest";
import type { Competition, League, TradeIdea, Trades } from "@/lib/api";
import { keys } from "@/lib/queries";
import { offlineClient, render } from "@/test/render";
import { BestTrade, Categories, JudgedAt, gain, undated, useJudgeWhenDue } from "@/panels/Scout";

describe("the best trade under the deadline item", () => {
  const competition = { key: "nfl-sleeper" } as Competition;
  const league = { league_id: "T1" } as League;
  const idea: TradeIdea = {
    team_id: "2",
    team: "Rival",
    giving: ["Puka Nacua"],
    receiving: ["Bijan Robinson"],
    playoffs: 0.9,
    playoffs_change: 0.02,
    their_playoffs_change: 0,
    points: 1,
    their_points: 1,
    playoff_points: 3.2,
    total: 12.4,
    their_playoffs: 0.4,
    pickup: "",
    form: [],
  };

  async function shown(trades: Trades) {
    const client = offlineClient();
    client.setQueryData(keys.trades(competition.key, league.league_id), trades);
    return (await render(<BestTrade competition={competition} league={league} />, client)).container;
  }

  it("names the Trades page's first offer, who to make it to and what it gains, with a way there", async () => {
    const container = await shown({ ideas: [idea, { ...idea, team: "Other" }], ranked_by: "total", pickup: "" });

    expect(container.textContent).toContain("Puka Nacua");
    expect(container.textContent).toContain("Bijan Robinson");
    expect(container.textContent).toContain("Rival");
    expect(container.textContent).not.toContain("Other");
    expect(container.textContent).toContain("+12.4");
    expect(container.querySelector("a")?.getAttribute("href")).toContain("trades");
  });

  it("says so when there is none to offer", async () => {
    const container = await shown({ ideas: [], ranked_by: "playoffs_change", pickup: "" });

    expect(container.textContent).toContain("No trades");
  });

  it("gains on the figure the Trades page orders by", () => {
    expect(gain(idea, "playoffs_change")).toContain("+2.0");
    expect(gain(idea, "total")).toContain("+12.4");
  });
});

function Judging({ due, scope, judge }: { due: boolean; scope: string; judge: { mutate: () => void; isPending: boolean } }) {
  useJudgeWhenDue(due, scope, judge);
  return null;
}

function counting() {
  const judge = { calls: 0, isPending: false, mutate: () => void judge.calls++ };
  return judge;
}

describe("judging again on arrival", () => {
  it("asks once for a league whose judgment is due, however often the page renders", async () => {
    const judge = counting();
    const page = await render(<Judging due scope="nfl:L1" judge={judge} />);
    await page.rerender(<Judging due scope="nfl:L1" judge={judge} />);

    expect(judge.calls).toBe(1);
  });

  it("asks again for another league", async () => {
    const judge = counting();
    const page = await render(<Judging due scope="nfl:L1" judge={judge} />);
    await page.rerender(<Judging due scope="nfl:L2" judge={judge} />);

    expect(judge.calls).toBe(2);
  });

  it("never asks where the judgment is not due, or one is already running", async () => {
    const judge = counting();
    await render(<Judging due={false} scope="nfl:L1" judge={judge} />);
    await render(<Judging due scope="nfl:L2" judge={{ ...judge, isPending: true }} />);

    expect(judge.calls).toBe(0);
  });
});

describe("Categories", () => {
  it("says who leads each category in words, and a dash where nobody does yet", async () => {
    const { container } = await render(
      <Categories
        theirs="Rival"
        lines={[
          { name: "PTS", mine: "520", theirs: "498", lead: "mine", win: null },
          { name: "BLK", mine: "12", theirs: "17", lead: "theirs", win: null },
          { name: "TO", mine: "-", theirs: "-", lead: null, win: null },
        ]}
      />,
    );
    const rows = [...container.querySelectorAll("[class*=border-b]")].map((r) => r.textContent ?? "");

    expect(rows.find((r) => r.startsWith("PTS"))).toMatch(/You$/);
    expect(rows.find((r) => r.startsWith("BLK"))).toMatch(/Them$/);
    expect(rows.find((r) => r.startsWith("TO"))).toMatch(/—$/);
    expect(container.textContent).not.toContain("Win");
  });

  it("gives each category's chance of winning where the week is forecast", async () => {
    const { container } = await render(
      <Categories
        theirs="Rival"
        lines={[
          { name: "PTS", mine: "520", theirs: "498", lead: "mine", win: 0.734 },
          { name: "DD", mine: "1", theirs: "0", lead: "mine", win: null },
        ]}
      />,
    );
    const rows = [...container.querySelectorAll("[class*=border-b]")].map((r) => r.textContent ?? "");

    expect(rows.find((r) => r.startsWith("PTS"))).toMatch(/You73%$/);
    expect(rows.find((r) => r.startsWith("DD"))).toMatch(/You—$/);
  });
});

describe("undated", () => {
  it("drops the week the stepper already shows, however the competition words it", () => {
    expect(undated("Week 11 · 19-23 Nov")).toBe("19-23 Nov");
    expect(undated("Gameweek 10 · in progress")).toBe("in progress");
    expect(undated("GW 2 · deadline Sat")).toBe("deadline Sat");
  });
});

describe("JudgedAt", () => {
  it("says stale once, beside when the list was judged, only while something on it has changed", async () => {
    const at = new Date().toISOString();
    const stale = await render(<JudgedAt at={at} stale />);
    const fresh = await render(<JudgedAt at={at} stale={false} />);

    expect(stale.container.textContent).toMatch(/^judged .+ · stale$/);
    expect(fresh.container.textContent).not.toContain("stale");
  });
});
