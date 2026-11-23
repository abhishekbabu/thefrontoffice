import { describe, expect, it } from "vitest";
import type { Spot } from "@/lib/api";
import { LineupCard, SideCard, underWay } from "@/components/ui/lineup";
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
    const { container } = await render(<SideCard side={side(scored("Waiting", "projected"))} label="You" started />);

    expect(container.textContent).toContain("Pts");
  });
});

describe("underWay", () => {
  it("is true from the first live or final score on either side", () => {
    const quiet = { name: "", record: "", detail: "", points: "", lineup: [spot("A")], bench: [], reserve: [], open_spots: 0 };
    const done = { ...quiet, bench: [{ ...spot("B"), scoring: "final" as const }] };

    expect(underWay(quiet, null)).toBe(false);
    expect(underWay(quiet, done)).toBe(true);
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
