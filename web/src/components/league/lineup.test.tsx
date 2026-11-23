import { describe, expect, it } from "vitest";
import type { Spot } from "@/lib/api";
import { LineupCard, SideCard, rowsOf } from "@/components/league/lineup";
import { render } from "@/test/render";
import { clock, startsAt } from "@/lib/format";

function spot(player: string, mark = "", today: Partial<Pick<Spot, "today" | "idle" | "kickoff">> = {}): Spot {
  return {
    player_id: player,
    slot: "",
    player,
    mark,
    detail: "MID · ARS vs LIV (2)",
    value: "6.0 xPts",
    tone: "neutral",
    today: "",
    idle: false,
    kickoff: null,
    scoring: null,
    scored: "",
    projection: "",
    line: [],
    ...today,
  };
}

describe("LineupCard", () => {
  it("shows an armband as a chip beside the name, not inside it", async () => {
    const { container } = await render(
      <LineupCard title="You" lineup={[spot("Haaland", "C"), spot("Isak", "VC"), spot("Rice")]} bench={[]} />,
    );

    expect(container.textContent).toContain("HaalandC");
    expect(container.textContent).toContain("IsakVC");
    expect(container.textContent).not.toContain("RiceC");
  });
});

describe("a day's lineup", () => {
  it("says on each row whether he plays today, so a starter sitting it out can be swapped", async () => {
    const { container } = await render(
      <LineupCard
        title="You"
        lineup={[spot("Plays", "", { today: "vs TOR today" }), spot("Sits", "", { today: "no game today", idle: true })]}
        bench={[]}
      />,
    );

    // Each said on its own player's row, in the lineup's order.
    expect(container.textContent).toMatch(/Plays.*vs TOR today.*Sits.*no game today/);
  });
});

describe("a day's lineup", () => {
  it("says the hour a game today tips off, beside the day", async () => {
    const tonight = new Date(Date.now() + 3_600_000).toISOString();
    const { container } = await render(
      <LineupCard title="You" lineup={[spot("Tonight", "", { today: "vs TOR today", kickoff: tonight })]} bench={[]} />,
    );

    expect(container.textContent).toContain(`vs TOR today ${clock(tonight)}`);
  });
});

describe("a week's lineup", () => {
  it("says when a game still to come starts", async () => {
    const thursday = new Date(Date.now() + 2 * 86_400_000).toISOString();
    const { container } = await render(
      <LineupCard title="You" lineup={[spot("Thursday", "", { kickoff: thursday })]} bench={[]} />,
    );

    expect(container.textContent).toContain(startsAt(thursday));
  });
});

describe("SideCard", () => {
  it("keeps the reserve slots apart from the bench", async () => {
    const side = {
      name: "Rival",
      record: "",
      detail: "",
      points: "",
      lineup: [spot("Starter")],
      bench: [spot("Backup")],
      reserve: [spot("Hurt")],
      open_spots: 0,
    };
    const { container } = await render(<SideCard side={side} label="Opponent" />);
    const text = container.textContent ?? "";

    expect(text.indexOf("Bench")).toBeLessThan(text.indexOf("Backup"));
    expect(text.indexOf("Backup")).toBeLessThan(text.indexOf("Reserve"));
    expect(text.indexOf("Reserve")).toBeLessThan(text.indexOf("Hurt"));
  });
});

describe("a side's header", () => {
  it("says the team's record ahead of anything else it reads", async () => {
    const side = { name: "Mine", record: "7-4", detail: "GW12 picks", points: "88", lineup: [spot("Starter")], bench: [], reserve: [], open_spots: 0 };
    const { container } = await render(<SideCard side={side} label="You" />);
    const text = container.textContent ?? "";

    expect(text).toContain("7-4");
    expect(text.indexOf("7-4")).toBeLessThan(text.indexOf("GW12 picks"));
    expect(text.indexOf("GW12 picks")).toBeLessThan(text.indexOf("88"));
  });
});

describe("open roster spots", () => {
  it("draws each spot nobody holds at the foot of the bench, and only there", async () => {
    const side = { name: "Mine", record: "", detail: "", points: "", lineup: [spot("Starter")], bench: [spot("Backup")], reserve: [], open_spots: 2 };
    const { container } = await render(<SideCard side={side} label="You" />);
    const text = container.textContent ?? "";

    expect(text).not.toContain("2 open");
    expect(text.split("Open roster spot")).toHaveLength(3);
    expect(text.indexOf("Backup")).toBeLessThan(text.indexOf("Open roster spot"));
  });

  it("shows the room even when nobody sits on the bench", async () => {
    const { container } = await render(<LineupCard title="You" lineup={[spot("Starter")]} bench={[]} openSpots={1} />);

    expect(container.textContent).toContain("Open roster spot");
    expect(container.textContent).not.toContain("Nobody on the bench.");
  });
});

describe("the points column", () => {
  const scored = (player: string, scoring: Spot["scoring"], points = ""): Spot => ({
    ...spot(player),
    scoring,
    scored: points,
    projection: "10.0",
  });
  const side = (...lineup: Spot[]) => ({ name: "Mine", record: "", detail: "", points: "", lineup, bench: [], reserve: [], open_spots: 0 });

  it("is not drawn before any game of the week kicks off", async () => {
    const { container } = await render(<SideCard side={side(scored("Waiting", "projected"))} label="You" />);

    expect(container.textContent).toContain("Proj");
    expect(container.textContent).not.toContain("Pts");
    expect(container.textContent).not.toContain("—");
  });

  it("is drawn once one has, with a dash for a player still to play", async () => {
    const { container } = await render(
      <SideCard side={side(scored("Playing", "live", "12.4"), scored("Waiting", "projected"))} label="You" />,
    );

    expect(container.textContent).toContain("Pts");
    expect(container.textContent).toContain("12.4");
    expect(container.textContent).toContain("—");
  });

  it("follows the caller where only the other side's game is under way", async () => {
    const waiting = side(scored("Waiting", "projected"));
    const playing = side(scored("Playing", "live", "12.4"));
    const { container } = await render(<SideCard side={waiting} label="You" rows={rowsOf(waiting, playing)} />);

    expect(container.textContent).toContain("Pts");
  });
});

describe("rowsOf", () => {
  const quiet = { name: "", record: "", detail: "", points: "", lineup: [spot("A")], bench: [], reserve: [], open_spots: 0 };

  it("is under way from the first live or final score on either side", () => {
    const done = { ...quiet, bench: [{ ...spot("B"), scoring: "final" as const }] };

    expect(rowsOf(quiet, null).started).toBe(false);
    expect(rowsOf(quiet, done).started).toBe(true);
  });

  it("makes room for a line of figures once anyone on either side has one", () => {
    const pts = { label: "PTS", value: "25", tone: "neutral" as const, url: "", better: null, hint: "" };
    const lined = { ...quiet, reserve: [{ ...spot("C"), line: [pts] }] };

    expect(rowsOf(quiet).line).toEqual([]);
    expect(rowsOf(quiet, lined).line).toEqual([pts]);
  });
});

describe("rows side by side", () => {
  const figure = (label: string, value: string) => ({ label, value, tone: "neutral" as const, url: "", better: null, hint: "" });
  const live = (player: string): Spot => ({
    ...spot(player, "C", { today: "@ UTA final" }),
    slot: "PG",
    scoring: "final",
    scored: "31.5",
    projection: "28.0",
    line: [figure("FG%", ".511"), figure("PTS", "25")],
  });
  const quiet = (player: string): Spot => ({ ...spot(player), slot: "PG", detail: "", value: "" });

  /** The two cards, yours then the opponent's. */
  const sides = (container: Element): [Element, Element] => {
    const [left, right] = container.children;
    if (!left || !right) throw new Error("expected two cards");
    return [left, right];
  };
  /** The fixed height each row's body is drawn at, in order: what sets how tall the row stands. */
  const rowBodies = (card: Element): string[] =>
    [...card.querySelectorAll("[data-row] > div")].map((el) => el.className.split(" ").filter((c) => /^h-/.test(c)).join());
  /** How many lines each player's row draws under his name: its detail, and its figures where any row has them. */
  const linesUnder = (card: Element): number[] =>
    [...card.querySelectorAll('[data-row="spot"]')].map((row) => row.querySelectorAll(".h-4").length);

  it("stand one height whatever each row holds, so slot N sits beside slot N", async () => {
    const mine = { name: "Mine", record: "", detail: "", points: "", lineup: [live("A"), quiet("B")], bench: [live("C")], reserve: [], open_spots: 1 };
    const theirs = { name: "Theirs", record: "", detail: "", points: "", lineup: [quiet("D"), quiet("E")], bench: [quiet("F"), quiet("G")], reserve: [], open_spots: 0 };
    const rows = rowsOf(mine, theirs);
    const { container } = await render(
      <>
        <SideCard side={mine} label="You" rows={rows} />
        <SideCard side={theirs} label="Opponent" rows={rows} />
      </>,
    );
    const [left, right] = sides(container);

    // Every row, a player's with a game, a score and a line, a bare one, or an open spot, takes the same fixed body.
    const bodies = [...rowBodies(left), ...rowBodies(right)];
    expect(bodies).toHaveLength(8);
    expect(new Set(bodies)).toEqual(new Set(["h-14"]));
    // The detail line and the figures' line are drawn on every player's row, empty or not.
    expect(linesUnder(left)).toEqual([2, 2, 2]);
    expect(linesUnder(right)).toEqual([2, 2, 2, 2]);
    // Both cards head the lineup and the bench with the categories, though only one side has a line.
    expect(left.textContent?.match(/FG%PTS/g)).toHaveLength(2);
    expect(right.textContent?.match(/FG%PTS/g)).toHaveLength(2);
  });

  it("are no taller for a game today, a kickoff or a mark than without", async () => {
    const plain = { name: "A", record: "", detail: "", points: "", lineup: [quiet("A")], bench: [], reserve: [], open_spots: 0 };
    const busy = {
      ...plain,
      lineup: [{ ...quiet("B"), mark: "C", today: "vs LAL today", kickoff: new Date(Date.now() + 3_600_000).toISOString() }],
    };
    const rows = rowsOf(plain, busy);
    const { container } = await render(
      <>
        <SideCard side={plain} label="You" rows={rows} />
        <SideCard side={busy} label="Opponent" rows={rows} />
      </>,
    );
    const [left, right] = sides(container);

    expect(rowBodies(left)).toEqual(["h-9"]);
    expect(rowBodies(right)).toEqual(["h-9"]);
    expect(linesUnder(left)).toEqual([1]);
    expect(linesUnder(right)).toEqual([1]);
    expect(right.textContent).toContain("vs LAL today");
  });
});

describe("a week played in categories", () => {
  const figure = (label: string, value: string) => ({ label, value, tone: "neutral" as const, url: "", better: null, hint: "" });
  const played = (player: string, fg: string, pts: string): Spot => ({
    ...spot(player),
    slot: "PG",
    line: [figure("FG%", fg), figure("PTS", pts)],
  });

  it("sets each category as a column under one heading, in place of a sentence", async () => {
    const side = { name: "Mine", record: "", detail: "", points: "", lineup: [played("A", ".511", "134"), played("B", "—", "0")], bench: [], reserve: [], open_spots: 0 };
    const { container } = await render(<SideCard side={side} label="You" />);

    expect(container.textContent).toContain("FG%PTS");
    const cells = [...container.querySelectorAll("[aria-label]")].map((el) => el.getAttribute("aria-label"));
    expect(cells).toEqual(["FG% .511", "PTS 134", "FG% —", "PTS 0"]);
  });

  it("keeps his week beside his line from a game today", async () => {
    const live = { ...played("A", ".500", "25"), value: "3 left", today: "vs TOR live" };
    const side = { name: "Mine", record: "", detail: "", points: "", lineup: [live], bench: [], reserve: [], open_spots: 0 };
    const { container } = await render(<SideCard side={side} label="You" />);

    expect(container.textContent).toContain("3 left");
    expect(container.querySelector('[aria-label="PTS 25"]')).not.toBeNull();
  });
});
