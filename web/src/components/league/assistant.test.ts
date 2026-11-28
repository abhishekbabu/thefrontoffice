import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, it } from "@effect/vitest";
import { Effect, Schema } from "effect";
import { http, HttpResponse } from "msw";
import { Assistant } from "@/components/league/assistant";
import { AssistantProvider, AssistantProviderMessage } from "@/components/league/assistant-provider";
import type { Route } from "@/lib/route";
import type { Competition, League, Subject, Turn } from "@/lib/types";
import { wire } from "@/lib/wire";
import { competitionOf } from "@/test/leagues";
import { page } from "@/test/play";
import { server } from "@/test/server";

const competition = competitionOf({ key: "nfl-sleeper" });
const league: League = { league_id: "900", name: "Dynasty", detail: "", url: "" };

const MATCHUP: Route = { page: "competition", competition: "nfl-sleeper", leagueId: "900", view: "matchup" };

/** A server holding one conversation per assistant opened, answering each question with every turn so far. */
function conversations() {
  const screens: Subject[][] = [];
  const turns: Turn[] = [];
  const state = { opened: 0, screens, turns };

  server.use(
    http.post("*/chats", () => {
      state.opened += 1;

      return HttpResponse.json({ chat_id: `chat-${state.opened}` });
    }),
    http.get("*/chats/:id", () => HttpResponse.json(state.turns)),
    http.post("*/chats/:id/turns", async ({ request }) => {
      // SAFETY: the assistant POSTs a turn as `{ message, on_screen }`.
      const { message, on_screen } = (await request.json()) as {
        message: string;
        on_screen: Subject[];
      };

      state.screens.push(on_screen);

      state.turns.push({ role: "you", text: message }, { role: "model", text: `About: ${message}` });

      return HttpResponse.json(state.turns);
    }),
  );

  return state;
}

const AskerMessage = UiSchema.TaggedEnum({ ClickedWhy: {} });

/** A "Why?" on a to-do row, far from the assistant in the tree. */
const Asker = Html.component({
  name: "Asker",
  model: Schema.Null,
  message: AskerMessage,
}).make({
  init: () => null,
  update: ($) =>
    $.send(
      AssistantProvider,
      AssistantProviderMessage.RequestedAsk({
        message: "Why bench him?",
        about: [{ subject: { kind: "task", key: "swap:a:b" }, label: "Swap" }],
      }),
    ),
  view: (h) => h.button.attr("type", "button").on("click", AskerMessage.ClickedWhy()).children("Why?"),
});

/** The shell's part of it: the provider over the page and the assistant beside it. */
const Shell = Html.component({
  name: "Shell",
  props: Schema.Struct({
    route: wire<Route>(),
    competition: Schema.NullOr(wire<Competition>()),
    league: Schema.NullOr(wire<League>()),
  }),
  model: Schema.Null,
  message: Schema.Never,
}).make({
  init: () => null,
  update: ($) => $.model,
  view: (h) =>
    AssistantProvider(h, {
      view: () => h.div.children(Asker(h, {}), Assistant(h, { key: "assistant", props: h.props })),
    }),
});

const openButton = HtmlLocator.role("button", { name: "Ask the assistant" });
const minimize = HtmlLocator.role("button", { name: "Minimize" });
const dock = HtmlLocator.role("region", { name: "Assistant" });
const box = HtmlLocator.role("textbox", { name: "Ask about this page" });

it.layer(page(), { buildPerTest: true })("the assistant", (it) => {
  it.effect("opens no conversation on the server until it is first opened", () =>
    Effect.gen(function* () {
      const state = conversations();

      const play = yield* HtmlPlay.make(Shell, {
        route: MATCHUP,
        competition,
        league,
      });

      assert.strictEqual(state.opened, 0);

      yield* play.click(openButton);

      yield* play.expect(box).toExist();

      assert.strictEqual(state.opened, 1);
    }),
  );

  it.effect("keeps the conversation where it was while minimized", () =>
    Effect.gen(function* () {
      const state = conversations();

      const play = yield* HtmlPlay.make(Shell, {
        route: MATCHUP,
        competition,
        league,
      });

      yield* play.click(openButton);

      yield* play.type(box, "Who starts?");

      yield* play.submit(box);

      yield* play.click(minimize);

      yield* play.expect(dock).toBeAbsent();

      yield* play.click(openButton);

      assert.include(play.root.text(), "About: Who starts?");

      assert.strictEqual(state.opened, 1);
    }),
  );

  it.effect("sends what is on screen: the page it is asked from", () =>
    Effect.gen(function* () {
      const state = conversations();

      const play = yield* HtmlPlay.make(Shell, {
        route: MATCHUP,
        competition,
        league,
      });

      yield* play.click(openButton);

      yield* play.expect(Locator.text("Matchup")).toExist();

      yield* play.type(box, "Who starts?");

      yield* play.submit(box);

      assert.deepStrictEqual(state.screens, [[{ kind: "page", key: "matchup" }]]);
    }),
  );

  it.effect("opens for a question handed to it, and sends it once beside the page", () =>
    Effect.gen(function* () {
      const state = conversations();

      const play = yield* HtmlPlay.make(Shell, {
        route: MATCHUP,
        competition,
        league,
      });

      yield* play.click(HtmlLocator.role("button", { name: "Why?" }));

      yield* play.expect(dock).toExist();

      assert.include(play.root.text(), "About: Why bench him?");

      assert.deepStrictEqual(state.screens, [
        [
          { kind: "page", key: "matchup" },
          { kind: "task", key: "swap:a:b" },
        ],
      ]);
    }),
  );

  it.effect("keeps the last league's conversation off the league pages", () =>
    Effect.gen(function* () {
      conversations();

      const play = yield* HtmlPlay.make(Shell, {
        route: MATCHUP,
        competition,
        league,
      });

      yield* play.click(openButton);

      play.root.setProps({
        route: { page: "settings" },
        competition: null,
        league: null,
      });

      yield* play.expect(Locator.text("Dynasty")).toExist();

      yield* play.expect(box).toExist();

      assert.include(play.root.text(), "No league open");
    }),
  );

  it.effect("asks for a league before there has been one", () =>
    Effect.gen(function* () {
      const play = yield* HtmlPlay.make(Shell, {
        route: { page: "landing" },
        competition: null,
        league: null,
      });

      yield* play.click(openButton);

      yield* play.expect(Locator.text("Open a league to ask about it.")).toExist();

      yield* play.expect(HtmlLocator.role("button", { name: "New conversation" })).toHaveAttribute("disabled", "");
    }),
  );
});
