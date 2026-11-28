import { HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import type { View } from "@effect/ui";
import type { Html } from "@effect/ui/html";
import { assert, describe, expect, it } from "@effect/vitest";
import { Effect } from "effect";
import { LineupCard, SideCard, rowsOf } from "@/components/league/lineup";
import { clock, startsAt } from "@/lib/times";
import type { Side, Spot } from "@/lib/types";
import { page, showing } from "@/test/play";

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

const sideOf = (extra: Partial<Side>): Side => ({
  name: "Mine",
  record: "",
  detail: "",
  points: "",
  lineup: [],
  bench: [],
  reserve: [],
  open_spots: 0,
  ...extra,
});

/** What `view` draws on a page of its own: a card, or nothing where it has nothing to show. */
const drawn = (view: (h: Html.H<never>) => View.Content<never> | null) =>
  HtmlPlay.make(
    showing((h) => h.div(view(h))),
    {},
  );

const locks = Locator.attr("aria-label", "Untouchable");

const classes = (node: Locator.Node) => (node.attrs?.class ?? "").split(" ");

const elementsOf = (node: Locator.Node) => (node.children ?? []).filter((child) => child.tag !== undefined);

it.layer(page(), { buildPerTest: true })("lineups", (it) => {
  describe("LineupCard", () => {
    it.effect("shows an armband as a chip beside the name, not inside it", () =>
      Effect.gen(function* () {
        const play = yield* drawn((h) =>
          LineupCard(h, { title: "You", lineup: [spot("Haaland", "C"), spot("Isak", "VC"), spot("Rice")], bench: [] }),
        );

        assert.include(play.root.text(), "HaalandC");

        assert.include(play.root.text(), "IsakVC");

        assert.notInclude(play.root.text(), "RiceC");
      }),
    );

    it.effect("carries a lock beside each of yours marked untouchable, on the bench too", () =>
      Effect.gen(function* () {
        const play = yield* drawn((h) =>
          LineupCard(h, {
            title: "You",
            lineup: [spot("Haaland"), spot("Isak")],
            bench: [spot("Rice")],
            untouchable: (id) => id === "Isak" || id === "Rice",
          }),
        );

        assert.lengthOf(play.root.all(locks), 2);
      }),
    );
  });

  describe("a day's lineup", () => {
    it.effect("says on each row whether he plays today, so a starter sitting it out can be swapped", () =>
      Effect.gen(function* () {
        const play = yield* drawn((h) =>
          LineupCard(h, {
            title: "You",
            lineup: [spot("Plays", "", { today: "vs TOR today" }), spot("Sits", "", { today: "no game today", idle: true })],
            bench: [],
          }),
        );

        // Each said on its own player's row, in the lineup's order.
        assert.match(play.root.text(), /Plays.*vs TOR today.*Sits.*no game today/);
      }),
    );

    it.effect("says the hour a game today tips off, beside the day", () =>
      Effect.gen(function* () {
        const tonight = new Date(Date.now() + 3_600_000).toISOString();

        const play = yield* drawn((h) =>
          LineupCard(h, { title: "You", lineup: [spot("Tonight", "", { today: "vs TOR today", kickoff: tonight })], bench: [] }),
        );

        assert.include(play.root.text(), `vs TOR today ${clock(tonight)}`);
      }),
    );
  });

  describe("a week's lineup", () => {
    it.effect("says when a game still to come starts", () =>
      Effect.gen(function* () {
        const thursday = new Date(Date.now() + 2 * 86_400_000).toISOString();

        const play = yield* drawn((h) =>
          LineupCard(h, { title: "You", lineup: [spot("Thursday", "", { kickoff: thursday })], bench: [] }),
        );

        assert.include(play.root.text(), startsAt(thursday));
      }),
    );
  });

  describe("SideCard", () => {
    it.effect("keeps the reserve slots apart from the bench", () =>
      Effect.gen(function* () {
        const side = sideOf({ name: "Rival", lineup: [spot("Starter")], bench: [spot("Backup")], reserve: [spot("Hurt")] });

        const play = yield* drawn((h) => SideCard(h, { side, label: "Opponent" }));

        const text = play.root.text();

        assert.isBelow(text.indexOf("Bench"), text.indexOf("Backup"));

        assert.isBelow(text.indexOf("Backup"), text.indexOf("Reserve"));

        assert.isBelow(text.indexOf("Reserve"), text.indexOf("Hurt"));
      }),
    );

    it.effect("carries a lock beside each of yours marked untouchable, in the lineup, bench and reserve", () =>
      Effect.gen(function* () {
        const side = sideOf({ lineup: [spot("Starter")], bench: [spot("Backup")], reserve: [spot("Hurt")] });

        const play = yield* drawn((h) => SideCard(h, { side, label: "You", untouchable: (id) => id !== "Starter" }));

        assert.lengthOf(play.root.all(locks), 2);
      }),
    );
  });

  describe("a side's header", () => {
    it.effect("says the team's record ahead of anything else it reads", () =>
      Effect.gen(function* () {
        const side = sideOf({ record: "7-4", detail: "GW12 picks", points: "88", lineup: [spot("Starter")] });

        const play = yield* drawn((h) => SideCard(h, { side, label: "You" }));

        const text = play.root.text();

        assert.include(text, "7-4");

        assert.isBelow(text.indexOf("7-4"), text.indexOf("GW12 picks"));

        assert.isBelow(text.indexOf("GW12 picks"), text.indexOf("88"));
      }),
    );
  });

  describe("open roster spots", () => {
    it.effect("draws each spot nobody holds at the foot of the bench, and only there", () =>
      Effect.gen(function* () {
        const side = sideOf({ lineup: [spot("Starter")], bench: [spot("Backup")], open_spots: 2 });

        const play = yield* drawn((h) => SideCard(h, { side, label: "You" }));

        const text = play.root.text();

        assert.notInclude(text, "2 open");

        assert.lengthOf(text.split("Open roster spot"), 3);

        assert.isBelow(text.indexOf("Backup"), text.indexOf("Open roster spot"));
      }),
    );

    it.effect("shows the room even when nobody sits on the bench", () =>
      Effect.gen(function* () {
        const play = yield* drawn((h) => LineupCard(h, { title: "You", lineup: [spot("Starter")], bench: [], openSpots: 1 }));

        assert.include(play.root.text(), "Open roster spot");

        assert.notInclude(play.root.text(), "Nobody on the bench.");
      }),
    );
  });

  describe("the points column", () => {
    const scored = (player: string, scoring: Spot["scoring"], points = ""): Spot => ({
      ...spot(player),
      scoring,
      scored: points,
      projection: "10.0",
    });

    const side = (...lineup: Spot[]) => sideOf({ lineup });

    it.effect("is not drawn before any game of the week kicks off", () =>
      Effect.gen(function* () {
        const play = yield* drawn((h) => SideCard(h, { side: side(scored("Waiting", "projected")), label: "You" }));

        assert.include(play.root.text(), "Proj");

        assert.notInclude(play.root.text(), "Pts");

        assert.notInclude(play.root.text(), "—");
      }),
    );

    it.effect("is drawn once one has, with a dash for a player still to play", () =>
      Effect.gen(function* () {
        const play = yield* drawn((h) =>
          SideCard(h, { side: side(scored("Playing", "live", "12.4"), scored("Waiting", "projected")), label: "You" }),
        );

        assert.include(play.root.text(), "Pts");

        assert.include(play.root.text(), "12.4");

        assert.include(play.root.text(), "—");
      }),
    );

    it.effect("follows the caller where only the other side's game is under way", () =>
      Effect.gen(function* () {
        const waiting = side(scored("Waiting", "projected"));
        const playing = side(scored("Playing", "live", "12.4"));

        const play = yield* drawn((h) => SideCard(h, { side: waiting, label: "You", rows: rowsOf(waiting, playing) }));

        assert.include(play.root.text(), "Pts");
      }),
    );
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
    const both = (mine: Side, theirs: Side) =>
      Effect.gen(function* () {
        const rows = rowsOf(mine, theirs);

        const play = yield* drawn((h) =>
          h.div
            .attr("data-testid", "both")
            .children(SideCard(h, { side: mine, label: "You", rows }), SideCard(h, { side: theirs, label: "Opponent", rows })),
        );

        const [left, right] = elementsOf(play.root.get(Locator.testId("both")));

        if (!left || !right) throw new Error("expected two cards");

        return [left, right] as const;
      });

    /** The fixed height each row's body is drawn at, in order: what sets how tall the row stands. */
    const rowBodies = (card: Locator.Node): string[] =>
      Locator.all(card, Locator.attr("data-row")).map((row) =>
        classes(elementsOf(row)[0] ?? {})
          .filter((c) => /^h-/.test(c))
          .join(),
      );

    /** How many lines each player's row draws under his name: its detail, and its figures where any row has them. */
    const linesUnder = (card: Locator.Node): number[] =>
      Locator.all(card, Locator.attr("data-row", "spot")).map(
        (row) => Locator.elements(row).filter((node) => node !== row && classes(node).includes("h-4")).length,
      );

    /** Rows drawn in each list, lineup then bench then reserve. */
    const perList = (card: Locator.Node): number[] =>
      Locator.elements(card)
        .filter((node) => elementsOf(node).some((child) => child.attrs?.["data-row"] !== undefined))
        .map((list) => elementsOf(list).length);

    it.effect("stand one height whatever each row holds, so slot N sits beside slot N", () =>
      Effect.gen(function* () {
        const [left, right] = yield* both(
          sideOf({ lineup: [live("A"), quiet("B")], bench: [live("C")], open_spots: 1 }),
          sideOf({ name: "Theirs", lineup: [quiet("D"), quiet("E")], bench: [quiet("F"), quiet("G")] }),
        );

        // Every row, a player's with a game, a score and a line, a bare one, or an open spot, takes the same fixed body.
        const bodies = [...rowBodies(left), ...rowBodies(right)];

        assert.lengthOf(bodies, 8);

        assert.deepStrictEqual(new Set(bodies), new Set(["h-14"]));

        // The detail line and the figures' line are drawn on every player's row, empty or not.
        assert.deepStrictEqual(linesUnder(left), [2, 2, 2]);

        assert.deepStrictEqual(linesUnder(right), [2, 2, 2, 2]);

        // Both cards head the lineup and the bench with the categories, though only one side has a line.
        assert.lengthOf(Locator.textOf(left).match(/FG%PTS/g) ?? [], 2);

        assert.lengthOf(Locator.textOf(right).match(/FG%PTS/g) ?? [], 2);
      }),
    );

    it.effect("are no taller for a game today, a kickoff or a mark than without", () =>
      Effect.gen(function* () {
        const plain = sideOf({ name: "A", lineup: [quiet("A")] });

        const busy = sideOf({
          name: "A",
          lineup: [{ ...quiet("B"), mark: "C", today: "vs LAL today", kickoff: new Date(Date.now() + 3_600_000).toISOString() }],
        });

        const [left, right] = yield* both(plain, busy);

        assert.deepStrictEqual(rowBodies(left), ["h-9"]);

        assert.deepStrictEqual(rowBodies(right), ["h-9"]);

        assert.deepStrictEqual(linesUnder(left), [1]);

        assert.deepStrictEqual(linesUnder(right), [1]);

        assert.include(Locator.textOf(right), "vs LAL today");
      }),
    );

    it.effect("pad the shorter side's lists, so each list starts level with the other side's", () =>
      Effect.gen(function* () {
        const [left, right] = yield* both(
          sideOf({ lineup: [quiet("A"), quiet("B"), quiet("C")], bench: [quiet("D")], open_spots: 1 }),
          sideOf({ name: "Theirs", lineup: [quiet("E")], bench: [quiet("F"), quiet("G"), quiet("H")], reserve: [quiet("I")] }),
        );

        const padding = (card: Locator.Node) => Locator.all(card, Locator.attr("data-row", "pad"));

        assert.deepStrictEqual(perList(left), [3, 3, 1]);

        assert.deepStrictEqual(perList(right), perList(left));

        // Both cards head a reserve list, though only one side has anybody in it.
        assert.include(Locator.textOf(left), "Reserve");

        // The blanks are as tall as a player's row and say nothing to a screen reader.
        assert.lengthOf(padding(left), 2);

        assert.lengthOf(padding(right), 2);

        assert.deepStrictEqual(new Set(rowBodies(left)), new Set(["h-9"]));

        assert.isTrue(padding(left).every((row) => row.attrs?.["aria-hidden"] === "true" && Locator.textOf(row) === ""));
      }),
    );
  });

  describe("a week played in categories", () => {
    const figure = (label: string, value: string) => ({ label, value, tone: "neutral" as const, url: "", better: null, hint: "" });

    const played = (player: string, fg: string, pts: string): Spot => ({
      ...spot(player),
      slot: "PG",
      line: [figure("FG%", fg), figure("PTS", pts)],
    });

    it.effect("sets each category as a column under one heading, in place of a sentence", () =>
      Effect.gen(function* () {
        const side = sideOf({ lineup: [played("A", ".511", "134"), played("B", "—", "0")] });

        const play = yield* drawn((h) => SideCard(h, { side, label: "You" }));

        assert.include(play.root.text(), "FG%PTS");

        const cells = play.root.all(Locator.attr("aria-label")).map((node) => node.attrs?.["aria-label"]);

        assert.deepStrictEqual(cells, ["FG% .511", "PTS 134", "FG% —", "PTS 0"]);
      }),
    );

    it.effect("keeps his week beside his line from a game today", () =>
      Effect.gen(function* () {
        const live = { ...played("A", ".500", "25"), value: "3 left", today: "vs TOR live" };

        const play = yield* drawn((h) => SideCard(h, { side: sideOf({ lineup: [live] }), label: "You" }));

        assert.include(play.root.text(), "3 left");

        yield* play.expect(Locator.attr("aria-label", "PTS 25")).toExist();
      }),
    );
  });
});

describe("rowsOf", () => {
  const quiet = sideOf({ name: "", lineup: [spot("A")] });

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
