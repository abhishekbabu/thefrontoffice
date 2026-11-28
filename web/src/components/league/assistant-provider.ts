/**
 * What the assistant shares with the page around it: whether it is open,
 * the question handed to it from elsewhere — a "Why?" — and what is open over
 * the page for it to see.
 *
 * Shared state rather than props, because the askers and the drawers are deep
 * inside a panel and the assistant beside the whole shell, and nothing between
 * them should have to carry what one tells the other. A drawer reports what it
 * shows while it is mounted (`report` in its `reads`), so closing it takes it
 * off screen with nothing to undo; an asker sends `RequestedAsk`.
 */
import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Schema } from "effect";
import { Shown } from "@/lib/screen";

/** A question somebody asked from elsewhere on the page — a "Why?" — for the assistant to send. */
export const Handed = Schema.Struct({ message: Schema.String, about: Schema.Array(Shown) });

export type Handed = typeof Handed.Type;

export const AssistantProviderMessage = UiSchema.TaggedEnum({
  /** A question handed over to open the assistant and send, with what it is about. */
  RequestedAsk: { message: Schema.String, about: Schema.Array(Shown) },
  /** The assistant opened or minimized, from its own controls. */
  RequestedDock: { open: Schema.Boolean },
  /** The handed question was sent. */
  TookAsked: {},
  /** What the drawers mounted now report showing. */
  ChangedOpened: { opened: Schema.Array(Shown) },
});

const Shared = Schema.Struct({ open: Schema.Boolean, asked: Schema.NullOr(Handed), opened: Schema.Array(Shown) });

export const AssistantProvider = Html.component({
  name: "AssistantProvider",
  model: Shared,
  message: AssistantProviderMessage,
  shares: {
    value: ({ model }) => model,
    schema: Shared,
    receives: ["RequestedAsk", "RequestedDock", "TookAsked"],
    collects: {
      schema: Schema.NullOr(Shown),
      onChange: (reports) =>
        AssistantProviderMessage.ChangedOpened({ opened: reports.filter((shown) => shown !== null) }),
    },
  },
  restore: false,
}).make({
  init: () => ({ open: false, asked: null, opened: [] }),
  update: {
    RequestedAsk: ($, { message, about }) => $.evolve({ open: true, asked: { message, about } }),
    RequestedDock: ($, { open }) => $.evolve({ open }),
    TookAsked: ($) => $.evolve({ asked: null }),
    ChangedOpened: ($, { opened }) => $.evolve({ opened }),
  },
});
