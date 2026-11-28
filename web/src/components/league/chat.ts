import { Command, Component, Subscription, UiSchema } from "@effect/ui";
import type { View } from "@effect/ui";
import { Html, HtmlCommand } from "@effect/ui/html";
import { Cause, Effect, Schema, Stream } from "effect";
import { AsyncResult } from "effect/reactivity";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Input } from "@/components/ui/controls/input";
import { ErrorNote } from "@/components/ui/error-note";
import { Label } from "@/components/ui/label";
import { Prose } from "@/components/ui/prose";
import { Busy } from "@/components/ui/state";
import { ApiError, api, isExpired } from "@/lib/api";
import { fetching } from "@/lib/queries/cache";
import { GetTurns, OpenChat } from "@/lib/queries/chat";
import type { Subject, Turn } from "@/lib/types";
import { cn } from "@/lib/utils";
import { wire } from "@/lib/wire";

/** A question, and what it was asked about. */
export const Asked = Schema.Struct({
  message: Schema.String,
  about: Schema.Array(wire<Subject>()),
});

export type Asked = typeof Asked.Type;

/** A turn as shown: the server's, or a question that failed, with why. */
type Shown = Turn & { error?: ApiError | undefined };

/** The same thing named twice is sent once. */
function unique(subjects: readonly Subject[]): Subject[] {
  return subjects.filter((s, i) => subjects.findIndex((t) => t.kind === s.kind && t.key === s.key) === i);
}

const sameAsked = (a: Asked | null, b: Asked | null) =>
  a !== null &&
  b !== null &&
  a.message === b.message &&
  a.about.length === b.about.length &&
  a.about.every((s, i) => s.kind === b.about[i]?.kind && s.key === b.about[i]?.key);

/** Whether a read of the turns failed on the server no longer holding the conversation. */
function expiredIn(result: AsyncResult.AsyncResult<unknown, ApiError>): boolean {
  if (!AsyncResult.isFailure(result)) return false;

  const error = Cause.squash(result.cause);

  return error instanceof ApiError && isExpired(error);
}

const conversation = {
  placeholder: Schema.String,
  /** Shown before anything has been said. */
  empty: Schema.optional(Schema.String),
  /** What is on screen as a question is asked, sent with it. */
  onScreen: Schema.Array(wire<Subject>()),
  /** A question handed over from elsewhere, to send as soon as the conversation can take it. */
  asked: Schema.NullOr(Asked),
};

const ChatProps = Schema.Struct({ chat: Schema.String, ...conversation });

const ChatModel = Schema.Struct({
  draft: Schema.String,
  /** The question on its way, until the server answers it. */
  pending: Schema.NullOr(Asked),
  /** A question the model did not answer: shown with why, never kept by the server. */
  failed: Schema.NullOr(Schema.Struct({ question: Schema.String, error: ApiError })),
  /** The handed question last sent, so a prop that stays put is sent once. */
  handled: Schema.NullOr(Asked),
});

const ChatMessage = UiSchema.TaggedEnum({
  UpdatedDraft: { value: Schema.String },
  SubmittedQuestion: {},
  /** A handed question is waiting, and the conversation can take it. */
  ArrivedAsked: {},
  /** The handed question is gone from the props: the same one handed again is a new question. */
  ClearedAsked: {},
  SucceededAskChat: { turns: wire<Turn[]>() },
  FailedAskChat: { asked: Asked, error: ApiError },
  ChangedTurns: { expired: Schema.Boolean },
});

type ChatMessage = typeof ChatMessage.Type;

/**
 * `Expired`: the server no longer holds the conversation, with the question
 * that went unasked. `TookAsked`: the handed question was sent.
 */
const ChatEvents = UiSchema.TaggedEnum({
  Expired: { unasked: Schema.NullOr(Asked) },
  TookAsked: {},
});

/**
 * Asks the next question with what is on screen. The server answers with the
 * whole conversation, which is written over the turns, so the page shows what
 * it holds; until then the question shows as asked, and no read of the turns
 * lands without it.
 */
class AskChat extends Command.Service<AskChat>()("chat/AskChat", {
  args: { chat: Schema.String, asked: Asked },
  success: ChatMessage,
  optimistic: ({ chat, asked }) => [
    GetTurns.patch({ chat }, (turns): Turn[] => [...turns, { role: "you", text: asked.message }]),
  ],
  writes: (result, { chat }) => (result._tag === "SucceededAskChat" ? [GetTurns.set({ chat }, result.turns)] : []),
}) {
  static readonly layer = this.toLayer(({ chat, asked }) =>
    fetching(() => api.ask(chat, asked.message, [...asked.about])).pipe(
      Effect.match({
        onSuccess: (turns) => ChatMessage.SucceededAskChat({ turns }),
        onFailure: (error) => ChatMessage.FailedAskChat({ asked, error }),
      }),
    ),
  );
}

/** The box is under the conversation, so keeping it in view keeps the newest turn in view too. */
const Box = Html.ref("Chat.box", "form");

const keepInView = HtmlCommand.ScrollIntoView.make({
  ref: Box,
  options: { block: "nearest", behavior: "smooth" },
}).pipe(Command.asNoop);

/**
 * A conversation with the model about whatever is on screen.
 *
 * The turns are the server's: it keeps them, so a conversation closed and
 * reopened shows what was said rather than a blank the server would carry on
 * from. Each question goes with `onScreen`, which the server briefs the model
 * on where it has not yet. `asked` is a question handed over from elsewhere —
 * a "Why?" on a to-do row — sent as soon as the conversation can take it,
 * with what it was about beside what is on screen; `TookAsked` says it has been.
 * `Expired` says the server no longer holds the conversation, with the
 * question that went unasked.
 */
const ChatNoDeps = Html.component({
  name: "Chat",
  props: ChatProps,
  model: ChatModel,
  message: ChatMessage,
  events: ChatEvents,
  queries: {
    history: {
      query: GetTurns,
      args: ({ props }) => ({ chat: props.chat }),
      onChange: (result) => ChatMessage.ChangedTurns({ expired: expiredIn(result) }),
    },
  },
  // A question on its way is not on its way after Back.
  restore: (model) => ({ ...model, pending: null }),
}).make({
  init: () => ({ draft: "", pending: null, failed: null, handled: null }),
  // Once per question handed over, and only once the conversation has been
  // read: sent before, its turn would be overwritten by the read landing.
  subscriptions: ({ model, props, queries }) => {
    const ready = AsyncResult.isSuccess(queries.history) && model.pending === null;

    return [
      ready &&
        props.asked !== null &&
        !sameAsked(props.asked, model.handled) &&
        Subscription.make("asked", props.asked.message, () => Stream.make(ChatMessage.ArrivedAsked())),
      props.asked === null &&
        model.handled !== null &&
        Subscription.make("cleared", Stream.make(ChatMessage.ClearedAsked())),
    ];
  },
  update: {
    UpdatedDraft: ($, { value }) => $.evolve({ draft: value }),
    SubmittedQuestion: ($) => {
      const message = $.model.draft.trim();

      if (!message || $.model.pending !== null) return $.model;

      const asked: Asked = { message, about: [...$.props.onScreen] };

      return $.evolve({ draft: "", pending: asked, failed: null })
        .run(AskChat.make({ chat: $.props.chat, asked }))
        .run(keepInView);
    },
    ArrivedAsked: ($) => {
      const handed = $.props.asked;

      if (handed === null || $.model.pending !== null || sameAsked(handed, $.model.handled)) return $.model;

      const asked: Asked = {
        message: handed.message,
        about: unique([...$.props.onScreen, ...handed.about]),
      };

      return $.evolve({ handled: handed, pending: asked, failed: null })
        .emit(ChatEvents.TookAsked())
        .run(AskChat.make({ chat: $.props.chat, asked }))
        .run(keepInView);
    },
    ClearedAsked: ($) => $.evolve({ handled: null }),
    SucceededAskChat: ($) => $.evolve({ pending: null }).run(keepInView),
    FailedAskChat: ($, { asked, error }) =>
      isExpired(error)
        ? $.evolve({ pending: null }).emit(ChatEvents.Expired({ unasked: asked }))
        : $.evolve({
            pending: null,
            failed: { question: asked.message, error },
          }).run(keepInView),
    ChangedTurns: ($, { expired }) => (expired ? $.emit(ChatEvents.Expired({ unasked: null })) : $.model),
  },
  view: (h, model) => {
    const history = h.queries.history;

    if (AsyncResult.isFailure(history) && !expiredIn(history))
      return ErrorNote(h, { error: Cause.squash(history.cause), class: "m-0" });

    if (!AsyncResult.isSuccess(history)) return Opening(h);

    const turns: Shown[] = [...history.value];

    if (model.failed !== null)
      turns.push({ role: "you", text: model.failed.question }, { role: "model", text: "", error: model.failed.error });

    const waiting = model.pending !== null;
    const { placeholder, empty } = h.props;

    // At least as tall as whatever holds it, so the box sits at the foot of the
    // panel rather than wherever the conversation so far happens to end.
    return h.div.class("flex min-h-full flex-col gap-3").children(
      turns.length === 0 &&
        !waiting &&
        empty !== undefined &&
        h.p.class("text-[13px] leading-relaxed text-muted-foreground").children(empty),
      turns.map((turn, i) =>
        Bubble(h, {
          key: String(i),
          role: turn.role,
          children: [
            turn.error !== undefined
              ? ErrorNote(h, {
                  error: turn.error,
                  class: "m-0",
                  key: `error-${i}`,
                })
              : turn.role === "model"
                ? Prose(h, { text: turn.text })
                : h.p.class("whitespace-pre-line").children(turn.text),
          ],
        }),
      ),
      // Where the answer will be, so waiting reads as the turn it is.
      waiting &&
        Bubble(h, {
          key: "thinking",
          role: "model",
          children: [h.span.class("text-muted-foreground").children(Busy(h).children("Thinking…"))],
        }),
      h.form
        .ref(Box)
        .class("mt-auto flex gap-2")
        .on("submit", ChatMessage.SubmittedQuestion())
        .children(
          Input(h, "flex-1")
            .attrs({ placeholder, "aria-label": placeholder })
            .value(model.draft)
            .on("input", ({ value }) => ChatMessage.UpdatedDraft({ value })),
          IconButton(h, {
            key: "ask",
            props: {
              label: "Ask",
              side: "left",
              variant: "primary",
              icon: "send-horizontal",
              disabled: !model.draft.trim() || waiting,
              class: "size-9",
            },
            onEmit: { Clicked: () => ChatMessage.SubmittedQuestion() },
          }),
        ),
    );
  },
});

const Chat = ChatNoDeps.pipe(Component.provide(AskChat.layer));

/** One turn: yours to the right in a tint, the model's at full width of the column. */
function Bubble<M, C extends View.Children<M>>(
  h: Html.H<M>,
  { key, role, children }: { key: string; role: Turn["role"]; children: C },
) {
  return h.div
    .key(key)
    .attr(
      "class",
      cn("flex max-w-[72ch] flex-col gap-0.5 text-[13.5px] leading-relaxed", role === "you" && "items-end self-end"),
    )
    .children(
      Label(h, { as: "div" }).children(role),
      h.div.attr("class", cn(role === "you" && "rounded-md bg-muted px-3 py-2") || undefined).children(children),
    );
}

function Opening<M>(h: Html.H<M>) {
  return h.span.class("text-[12.5px] text-muted-foreground").children(Busy(h).children("Opening…"));
}

const AssistantChatMessage = UiSchema.TaggedEnum({
  ExpiredChat: { unasked: Schema.NullOr(Asked) },
  TookChatAsked: {},
});

/** `TookAsked`: the handed question was sent. */
export const AssistantChatEvents = UiSchema.TaggedEnum({ TookAsked: {} });

/**
 * Drops the kept conversation, so it is opened again: the kept id is the one
 * the server no longer knows.
 */
class ReopenChat extends Command.Service<ReopenChat>()("chat/ReopenChat", {
  args: {
    competition: Schema.String,
    league: Schema.String,
    generation: Schema.Number,
  },
  invalidates: (args) => [OpenChat.entry(args)],
}) {
  static readonly layer = this.toLayer(() => Effect.void);
}

/**
 * The assistant's conversation in one league, opened on the server the first
 * time it is shown, then asked like any chat.
 *
 * Kept for the session per league and `generation` — a new conversation is
 * the next generation — so minimizing, moving page or switching league and
 * back finds the same conversation rather than starting a new one on the
 * server, until the server says it no longer holds it: then a fresh one is
 * opened and the question that went unasked is asked there. For the session
 * (`OpenChat` is never collected), not for the cache's default five minutes,
 * which would drop the id and open a blank conversation beside the one the
 * server still held.
 */
const AssistantChatNoDeps = Html.component({
  name: "AssistantChat",
  props: Schema.Struct({
    ...conversation,
    competition: Schema.String,
    league: Schema.String,
    generation: Schema.Number,
  }),
  model: Schema.Struct({ unasked: Schema.NullOr(Asked) }),
  message: AssistantChatMessage,
  events: AssistantChatEvents,
  queries: {
    thread: {
      query: OpenChat,
      args: ({ props }) => ({
        competition: props.competition,
        league: props.league,
        generation: props.generation,
      }),
    },
  },
}).make({
  init: () => ({ unasked: null }),
  update: {
    ExpiredChat: ($, { unasked }) =>
      $.evolve({ unasked }).run(
        ReopenChat.make({
          competition: $.props.competition,
          league: $.props.league,
          generation: $.props.generation,
        }),
      ),
    TookChatAsked: ($) => $.evolve({ unasked: null }).emit(AssistantChatEvents.TookAsked()),
  },
  view: (h, model) => {
    const thread = h.queries.thread;

    if (AsyncResult.isFailure(thread)) return ErrorNote(h, { error: Cause.squash(thread.cause), class: "m-0" });

    // Waiting is a conversation being opened again: the id still held is the dropped one.
    if (!AsyncResult.isSuccess(thread) || thread.waiting) return Opening(h);

    const chat = thread.value.chat_id;
    const { placeholder, empty, onScreen, asked } = h.props;

    return Chat(h, {
      key: chat,
      props: {
        chat,
        placeholder,
        empty,
        onScreen,
        asked: model.unasked ?? asked,
      },
      onEmit: {
        Expired: ({ unasked }) => AssistantChatMessage.ExpiredChat({ unasked }),
        TookAsked: () => AssistantChatMessage.TookChatAsked(),
      },
    });
  },
});

export const AssistantChat = AssistantChatNoDeps.pipe(Component.provide(ReopenChat.layer));
