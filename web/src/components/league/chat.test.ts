import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { assert, it } from "@effect/vitest";
import { Effect, Schema } from "effect";
import { TestClock } from "effect/testing";
import { http, HttpResponse } from "msw";
import { AssistantChat, AssistantChatEvents, type Asked } from "@/components/league/chat";
import type { Subject, Turn } from "@/lib/types";
import { elementHost, page } from "@/test/play";
import { server as msw } from "@/test/server";

const ASKED: Turn[] = [
  { role: "you", text: "Why bench him?" },
  { role: "model", text: "He has no fixture." },
];

/**
 * A server holding one conversation per assistant opened: `opened` counts
 * them, `screens` records what each question was asked with, and each
 * follow-up answers with every turn so far, as the API does. `expired` is a
 * conversation it no longer holds.
 */
function server(said: Turn[] = [], expired?: string) {
  const screens: Subject[][] = [];
  const state = { opened: 0, turns: [...said], screens };

  msw.use(
    http.all("*", async ({ request }) => {
      const path = new URL(request.url).pathname;

      if (path.endsWith("/chats")) {
        state.opened += 1;

        return HttpResponse.json({ chat_id: `chat-${state.opened}` });
      }

      if (expired && path.endsWith(`/${expired}/turns`) && request.method === "POST") {
        return HttpResponse.json({ detail: "Gone.", code: "chat_expired", remedy: null }, { status: 404 });
      }

      if (request.method === "POST") {
        // SAFETY: the assistant POSTs a turn as `{ message, on_screen }`.
        const { message, on_screen } = (await request.json()) as {
          message: string;
          on_screen: Subject[];
        };

        state.screens.push(on_screen);

        state.turns.push({ role: "you", text: message }, { role: "model", text: `About: ${message}` });
      }

      return HttpResponse.json(state.turns);
    }),
  );

  return state;
}

/** Every element the conversation asked the browser to scroll into view. */
const scrolled: Element[] = [];

const WEEK: Subject = { kind: "page", key: "matchup" };
const ITEM: Subject = { kind: "task", key: "swap:a:b" };

const props = (asked: Asked | null = null) => ({
  competition: "nfl-sleeper",
  league: "900",
  generation: 0,
  onScreen: [WEEK],
  asked,
  placeholder: "Ask",
});

const box = HtmlLocator.role("textbox", { name: "Ask" });

const ClosingMessage = UiSchema.TaggedEnum({ ClickedToggle: {} });

/** The conversation as the assistant hosts it: closed, and opened again, on one page. */
const Closing = Html.component({
  name: "Closing",
  model: Schema.Boolean,
  message: ClosingMessage,
}).make({
  init: () => true,
  update: ($) => !$.model,
  view: (h, shown) =>
    h.div.children(
      h.button.attr("type", "button").on("click", ClosingMessage.ClickedToggle()).children("Toggle"),
      shown && AssistantChat(h, { props: props() }),
    ),
});

const toggle = HtmlLocator.role("button", { name: "Toggle" });

it.layer(
  page(
    "/",
    elementHost((element) => {
      scrolled.push(element);
    }),
  ),
  { buildPerTest: true },
)("the assistant's conversation", (it) => {
  it.effect("finds the same conversation when reopened long after it was closed", () =>
    Effect.gen(function* () {
      // Past the cache's five-minute default, which dropped the id and opened
      // a blank conversation beside the one the server still held.
      const state = server(ASKED);

      const play = yield* HtmlPlay.make(Closing, {});

      yield* play.click(toggle);

      yield* play.expect(box).toBeAbsent();

      yield* TestClock.adjust("30 minutes");

      yield* play.click(toggle);

      assert.strictEqual(state.opened, 1);

      assert.include(play.root.text(), "He has no fixture.");
    }),
  );

  it.effect("does not scroll to the turns it reads back on opening", () =>
    Effect.gen(function* () {
      // In the player drawer that carried the page past everything above the chat.
      server(ASKED);

      scrolled.length = 0;

      const play = yield* HtmlPlay.make(AssistantChat, props());

      assert.include(play.root.text(), "He has no fixture.");

      assert.lengthOf(scrolled, 0);
    }),
  );

  it.effect("keeps a question asked here, and its answer, in view", () =>
    Effect.gen(function* () {
      server(ASKED);

      scrolled.length = 0;

      const play = yield* HtmlPlay.make(AssistantChat, props());

      yield* play.type(box, "And next week?");

      yield* play.submit(box);

      assert.include(play.root.text(), "About: And next week?");

      assert.isAbove(scrolled.length, 0);
    }),
  );

  it.effect("shows the conversation the server answers with rather than a copy of its own", () =>
    Effect.gen(function* () {
      const state = server(ASKED);

      const play = yield* HtmlPlay.make(AssistantChat, props());

      // Asked since from another tab: only the server's record has it.
      state.turns.push({ role: "you", text: "Elsewhere?" }, { role: "model", text: "Yes." });

      yield* play.type(box, "And next week?");

      yield* play.submit(box);

      assert.match(play.root.text(), /Why bench him\?.*Elsewhere\?.*And next week\?/);
    }),
  );

  it.effect("sends each question with what is on screen", () =>
    Effect.gen(function* () {
      const state = server();

      const play = yield* HtmlPlay.make(AssistantChat, props());

      yield* play.type(box, "Who starts?");

      yield* play.submit(box);

      assert.deepStrictEqual(state.screens, [[WEEK]]);
    }),
  );

  it.effect("sends a question handed over with what it is about beside the page, once", () =>
    Effect.gen(function* () {
      const state = server();

      const play = yield* HtmlPlay.make(AssistantChat, props({ message: "Why?", about: [ITEM, WEEK] }));

      assert.include(play.root.text(), "About: Why?");

      assert.deepStrictEqual(state.screens, [[WEEK, ITEM]]);

      assert.deepStrictEqual(play.root.emitted, [AssistantChatEvents.TookAsked()]);
    }),
  );

  it.effect("asks a question the server's dropped conversation never took in a fresh one", () =>
    Effect.gen(function* () {
      const state = server([], "chat-1");

      const play = yield* HtmlPlay.make(AssistantChat, props());

      yield* play.type(box, "Still there?");

      yield* play.submit(box);

      assert.strictEqual(state.opened, 2);

      assert.include(play.root.text(), "About: Still there?");
    }),
  );
});
