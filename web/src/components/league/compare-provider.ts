/**
 * The players being compared in each league, shared with every page.
 *
 * A player is added from wherever his drawer opens — the roster, a move, a
 * trade — and the Compare page shows the same list, so the list lives above
 * them all: a reader reads `ids` for its league, and sends `RequestedAdd`,
 * `RequestedRemove` or `RequestedSet` to change it. Each change is written
 * back to the browser, so it outlives the page.
 */
import { Command, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Effect, Schema } from "effect";
import { kept, writeCompared } from "@/lib/compare";

export const CompareProviderMessage = UiSchema.TaggedEnum({
  RequestedAdd: { scope: Schema.String, id: Schema.String },
  RequestedRemove: { scope: Schema.String, id: Schema.String },
  RequestedSet: { scope: Schema.String, ids: Schema.Array(Schema.String) },
});

const Compared = Schema.Record(Schema.String, Schema.Array(Schema.String));

/** Writes one league's comparison to the browser. */
const KeepCompared = Command.make(
  "KeepCompared",
  { args: { scope: Schema.String, ids: Schema.Array(Schema.String) } },
  ({ scope, ids }) => Effect.sync(() => writeCompared(scope, ids)),
);

export const CompareProvider = Html.component({
  name: "CompareProvider",
  /** What the browser held as the app started (`readCompared`). */
  props: Schema.Struct({ initial: Schema.optional(Compared) }),
  model: Schema.Struct({ compared: Compared }),
  message: CompareProviderMessage,
  shares: {
    value: ({ model }) => model.compared,
    schema: Compared,
    receives: ["RequestedAdd", "RequestedRemove", "RequestedSet"],
  },
}).make({
  init: ($) => ({ compared: $.props.initial ?? {} }),
  update: ($, message) => {
    const now = $.model.compared[message.scope] ?? [];

    const next = CompareProviderMessage.match(message, {
      RequestedAdd: ({ id }) => kept([...now, id]),
      RequestedRemove: ({ id }) => now.filter((x) => x !== id),
      RequestedSet: ({ ids }) => kept(ids),
    });

    return $.evolve({ compared: (compared) => ({ ...compared, [message.scope]: next }) }).run(
      KeepCompared.make({ scope: message.scope, ids: next }).pipe(Command.asNoop),
    );
  },
});
