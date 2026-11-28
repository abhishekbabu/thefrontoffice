import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { assert, describe, expect, it } from "@effect/vitest";
import { Effect, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { http, HttpResponse } from "msw";
import { ActionList, ActionListEvents, ActionListProps, opener } from "@/components/league/actions";
import { AssistantProvider } from "@/components/league/assistant-provider";
import { staleVerdicts } from "@/components/league/verdicts";
import { GetWeek } from "@/lib/queries/week";
import type { Comparing } from "@/lib/comparing";
import type { Action, ItemDecision, MovePlayer, TaskVerdict } from "@/lib/types";
import { wire } from "@/lib/wire";
import { competitionOf } from "@/test/leagues";
import { page, showing } from "@/test/play";
import { server } from "@/test/server";

const competition = competitionOf({ key: "nfl-sleeper" });

function action(key: string, verdict: TaskVerdict | null = null, stale = false): Action {
  return {
    kind: "waiver",
    urgency: "soon",
    key,
    title: `Pick up ${key}`,
    reason: "Projects 7.56, best DEF available.",
    when: "",
    player_id: "",
    replaces: "",
    drop: "",
    pickup: null,
    win_change: null,
    evidence: [],
    players: [],
    verdict,
    stale,
    mark: { hidden: null, snoozed_until: null, resurfaced: false },
    chance: null,
    fingerprint: key,
  };
}

const dismissed = (item: Action): Action => ({ ...item, mark: { hidden: "dismissed", snoozed_until: null, resurfaced: false } });

const said = (decision: TaskVerdict["decision"], reason: string): TaskVerdict => ({ task: "T1", decision, reason });

/** A page reading the week, with its to-do list drawn from it, as the matchup has. */
const Week = Html.component({
  name: "Week",
  model: Schema.Null,
  message: Schema.Never,
  queries: { week: { query: GetWeek, args: () => ({ competition: competition.key, league: "T1" }) } },
}).make({
  init: () => null,
  update: ($) => $.model,
  view: (h) =>
    AsyncResult.isSuccess(h.queries.week)
      ? ActionList(h, { props: listOf(h.queries.week.value.actions ?? [], { decides: true }) })
      : h.div(),
});

const ListingMessage = UiSchema.TaggedEnum({
  RequestedOpenPlayerList: { id: Schema.String },
  RequestedCompareList: { comparing: wire<Comparing>() },
});

/** The list as a page holds it, its slot placed and its requests passed on as the page would hear them. */
const Listing = Html.component({
  name: "Listing",
  props: ActionListProps,
  model: Schema.Null,
  message: ListingMessage,
  events: ActionListEvents,
}).make({
  init: () => null,
  update: {
    RequestedOpenPlayerList: ($, { id }) => $.emit(ActionListEvents.RequestedOpenPlayer({ id })),
    RequestedCompareList: ($, { comparing }) => $.emit(ActionListEvents.RequestedCompare({ comparing })),
  },
  view: (h) =>
    ActionList(h, {
      props: h.props,
      onEmit: {
        RequestedOpenPlayer: ({ id }) => ListingMessage.RequestedOpenPlayerList({ id }),
        RequestedCompare: ({ comparing }) => ListingMessage.RequestedCompareList({ comparing }),
      },
    }),
});

/** What the assistant was handed, read from its provider: a "Why?" is far from the assistant in the tree. */
const Asked = Html.component({
  name: "Asked",
  model: Schema.Null,
  message: Schema.Never,
  reads: { provider: AssistantProvider },
}).make({
  init: () => null,
  update: ($) => $.model,
  view: (h) => {
    const asked = h.reads.provider.asked;

    return h.p(asked ? `${asked.message} (${asked.about.map((s) => `${s.subject.kind} ${s.subject.key}`).join(", ")})` : "");
  },
});

const Asking = showing((h) =>
  AssistantProvider(h, {
    view: () => h.div(ActionList(h, { props: listOf([action("a")], { asks: true }) }), Asked(h, {})),
  }),
);

/** The first of several matches: every row has its own. */
const first = (locator: Locator.Locator): Locator.Locator => ({
  ...locator,
  description: `first ${locator.description}`,
  all: (root) => locator.all(root).slice(0, 1),
});

const listOf = (actions: readonly Action[], extra: Partial<ActionListProps> = {}): ActionListProps => ({
  competition,
  league: "T1",
  actions,
  ...extra,
});

/** The text of each item in the list, in order: the rows of the `<ol>`, not those under Hidden. */
const listed = (root: { all: (locator: Locator.Locator) => ReadonlyArray<Locator.Node> }) =>
  root.all(Locator.inside(Locator.tag("ol"), Locator.tag("li"))).map((row) => Locator.textOf(row));

const player = (
  side: MovePlayer["side"],
  name: string,
  held: MovePlayer["held"],
  [snaps, proj, opp]: [string, string, string],
): MovePlayer => ({
  side,
  player_id: name,
  name,
  position: "WR",
  team: "TEN",
  held,
  figures: [
    { label: "Snap% (L3)", value: snaps, tone: "neutral", url: "", better: null, hint: "" },
    { label: "Proj", value: proj, tone: "neutral", url: "", better: null, hint: "" },
    { label: "Opp", value: opp, tone: "good", url: "", better: null, hint: "" },
  ],
});

it.layer(page(), { buildPerTest: true })("ActionList", (it) => {
  describe("pickups", () => {
    it.effect("says in words whether an add streams this week or is kept, and nothing for any other item", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(
          Listing,
          listOf([
            { ...action("stream"), pickup: "streamer" },
            { ...action("keep"), pickup: "keeper", when: "Thu 26 Nov" },
            action("plain"),
          ]),
        );

        const rows = listed(play.root);

        assert.include((rows[0] ?? ""), "Streamer");

        assert.include((rows[1] ?? ""), "Keeper");

        assert.include((rows[1] ?? ""), "Thu 26 Nov");

        assert.notMatch((rows[2] ?? ""), /Streamer|Keeper/);
      }),
    );
  });

  describe("verdicts", () => {
    it.effect("shows an agreement as a chip alone, without the model's sentence", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(
          Listing,
          listOf([action("lions", said("AGREE", "Lions give 7.56 pts vs zero from Packers"))]),
        );

        assert.include(play.root.text(), "Agree");

        assert.notInclude(play.root.text(), "zero from Packers");
      }),
    );

    it.effect("shows the reason where the model overrules or waits", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(
          Listing,
          listOf([
            action("a", said("OVERRULE", "His snaps fell to a third.")),
            action("b", said("WAIT", "Questionable; inactives Sunday.")),
          ]),
        );

        assert.include(play.root.text(), "His snaps fell to a third.");

        assert.include(play.root.text(), "Questionable; inactives Sunday.");
      }),
    );

    it.effect("says stale on no row: the list's header says it once", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(
          Listing,
          listOf([action("a", said("OVERRULE", "No."), true), action("b", said("AGREE", "Yes."), true)]),
        );

        assert.notInclude(play.root.text().toLowerCase(), "stale");
      }),
    );
  });

  describe("putting an item aside", () => {
    it.effect("takes it out of the list and under Hidden, and back again on restore", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Listing, listOf([action("a"), action("b")]));

        play.root.setProps(listOf([action("a"), dismissed(action("b"))]));

        yield* play.expect(Locator.text("Hidden (1)")).toExist();

        assert.lengthOf(listed(play.root), 1);

        assert.include(listed(play.root)[0] ?? "", "Pick up a");

        play.root.setProps(listOf([action("a"), action("b")]));

        yield* play.expect(Locator.text("Hidden")).toBeAbsent();

        assert.lengthOf(listed(play.root), 2);
      }),
    );

    it.effect("says nothing is left once the last item is put aside", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Listing, listOf([action("a")]));

        play.root.setProps(listOf([dismissed(action("a"))]));

        yield* play.expect(Locator.text("Nothing left.")).toExist();

        assert.lengthOf(listed(play.root), 0);
      }),
    );

    it.effect("keeps a dismissal with the item as it read, and moves it under Hidden on the page's week", () =>
      Effect.gen(function* () {
        const decided: ItemDecision[] = [];

        server.use(
          http.get("*/week", () => HttpResponse.json({ actions: [action("a"), action("b")] })),
          http.post<never, ItemDecision>("*/items", async ({ request }) => {
            decided.push(await request.json());

            return HttpResponse.json({ hidden: "dismissed", snoozed_until: null, resurfaced: false });
          }),
        );

        const play = yield* HtmlPlay.make(Week, {});

        yield* play.click(first(HtmlLocator.role("button", { name: "Dismiss until it changes" })));

        assert.deepStrictEqual(decided, [{ key: "a", decision: "dismiss", fingerprint: "a", until: null }]);

        yield* play.expect(Locator.text("Hidden (1)")).toExist();

        assert.lengthOf(listed(play.root), 1);

        assert.include(listed(play.root)[0] ?? "", "Pick up b");
      }),
    );

    it.effect("offers how long to snooze for inline, and snoozes for the one picked, from now", () =>
      Effect.gen(function* () {
        const decided: ItemDecision[] = [];

        server.use(
          http.post<never, ItemDecision>("*/items", async ({ request }) => {
            decided.push(await request.json());

            return HttpResponse.json({ hidden: "snoozed", snoozed_until: null, resurfaced: false });
          }),
        );

        const play = yield* HtmlPlay.make(Listing, listOf([action("a")], { decides: true }));

        yield* play.expect(HtmlLocator.role("button", { name: "3 hours" })).toBeAbsent();

        yield* play.click(HtmlLocator.role("button", { name: "Snooze" }));

        yield* play.click(HtmlLocator.role("button", { name: "3 hours" }));

        // The test's clock stands at the epoch: three hours on from it.
        assert.deepStrictEqual(decided, [
          { key: "a", decision: "snooze", fingerprint: "", until: new Date(3 * 3600_000).toISOString() },
        ]);

        yield* play.expect(HtmlLocator.role("button", { name: "3 hours" })).toBeAbsent();
      }),
    );

    it.effect("offers nothing to dismiss, snooze or restore where decisions cannot be kept", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Listing, listOf([action("a"), dismissed(action("b"))]));

        yield* play.expect(HtmlLocator.role("button", { name: "Dismiss until it changes" })).toBeAbsent();

        yield* play.expect(Locator.attr("aria-label", "Restore")).toBeAbsent();
      }),
    );
  });

  describe("a move between two players", () => {
    const dike = player("in", "Chimere Dike", "free agent", ["66%", "9.88", "vs DAL, 6th-easiest"]);

    const swap: Action = {
      ...action("dike"),
      players: [dike, player("out", "Antonio Williams", "bench", ["40%", "8.20", "vs KC, 2nd-toughest"])],
    };

    it.effect("lines the two players up in columns, each figure on its own row read across", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Listing, listOf([swap]));

        const rows = play.root
          .all(Locator.inside(Locator.tag("tbody"), Locator.tag("tr")))
          .map((row) => Locator.all(row, Locator.tag("td")).map((cell) => Locator.textOf(cell)));

        assert.deepStrictEqual(rows, [
          ["Snap% (L3)", "66%", "40%"],
          ["Proj", "9.88", "8.20"],
          ["Opp", "vs DAL, 6th-easiest", "vs KC, 2nd-toughest"],
        ]);
      }),
    );

    it.effect("says which way each player goes and where he stands, in words", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Listing, listOf([swap]));

        const heads = play.root
          .all(Locator.inside(Locator.tag("thead"), Locator.tag("th")))
          .map((cell) => Locator.textOf(cell));

        assert.deepStrictEqual(heads, ["", "InChimere Dikefree agent", "OutAntonio Williamsbench"]);
      }),
    );

    it.effect("keeps a move of one player compact, with no table", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Listing, listOf([{ ...action("one"), players: [dike] }]));

        yield* play.expect(Locator.tag("table")).toBeAbsent();
      }),
    );
  });

  describe("opening an item", () => {
    it.effect("asks the page to open the player it is about", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Listing, listOf([{ ...action("lions"), player_id: "DET" }]));

        yield* play.click(HtmlLocator.role("button", { name: /Pick up lions/ }));

        assert.deepStrictEqual(play.root.emitted, [ActionListEvents.RequestedOpenPlayer({ id: "DET" })]);
      }),
    );
  });

  describe("asking why", () => {
    it.effect("hands the assistant the question about the item, with the item as what it is about", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Asking, {});

        yield* play.click(HtmlLocator.role("button", { name: "Why this move?" }));

        yield* play.expect(Locator.text('Why "Pick up a", and what would change your mind? (task a)')).toExist();
      }),
    );

    it.effect("is offered only where a model is configured", () =>
      Effect.gen(function* () {
        const play = yield* HtmlPlay.make(Listing, listOf([action("a")]));

        yield* play.expect(HtmlLocator.role("button", { name: "Why this move?" })).toBeAbsent();
      }),
    );
  });
});

describe("staleVerdicts", () => {
  it("is true while any shown item's verdict is stale, and ignores hidden ones and items never judged", () => {
    const hidden = dismissed(action("h", said("AGREE", ""), true));

    expect(staleVerdicts([action("a", said("AGREE", ""), true)])).toBe(true);
    expect(staleVerdicts([hidden, action("b", null, true), action("c", said("AGREE", ""))])).toBe(false);
  });
});

describe("what an item opens", () => {
  const dike = player("in", "Chimere Dike", "free agent", ["66%", "9.88", "vs DAL"]);
  const williams = player("out", "Antonio Williams", "bench", ["40%", "8.20", "vs KC"]);
  const open = (id: string) => ({ open: id });
  const compare = (comparing: Comparing) => ({ compare: comparing });

  it("opens the players a move weighs side by side, each said to be coming in or going out", () => {
    const swap: Action = { ...action("dike"), player_id: dike.player_id, players: [dike, williams] };

    expect(opener<object>(swap, open, compare)).toEqual({
      compare: {
        ids: ["Chimere Dike", "Antonio Williams"],
        title: "Pick up dike",
        tags: { "Chimere Dike": "In", "Antonio Williams": "Out" },
      },
    });
  });

  it("opens the one player an item is about, and nothing where it is about nobody", () => {
    const single: Action = { ...action("lions"), player_id: "DET", players: [] };

    expect(opener<object>(single, open, compare)).toEqual({ open: "DET" });
    expect(opener<object>(action("trade"), open, compare)).toBeUndefined();
  });

  it("falls back to the one player where the page cannot compare", () => {
    const swap: Action = { ...action("dike"), player_id: dike.player_id, players: [dike, williams] };

    expect(opener(swap, open)).toEqual({ open: "Chimere Dike" });
  });
});
