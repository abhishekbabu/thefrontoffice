/**
 * Something on the page that explains itself on hover and on focus: an
 * abbreviated status, a name whose pricing is off his projection, a record
 * that is not the one held that week.
 *
 * Four places wrapped a span by hand for this, and one forgot the accessible
 * name. Focusable, because a note a keyboard cannot reach is a note only a
 * mouse gets; `name` is what a screen reader hears — the text and its note
 * together. `dotted` underlines plain text so it reads as having more to say;
 * a badge already looks like it does.
 *
 * What it explains is passed as its `content` slot. It is a button only to be
 * focusable and to carry the tooltip; it looks like the text it holds and
 * does nothing when pressed.
 */
import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Schema } from "effect";
import { Side, Tip } from "@/components/ui/overlays/tooltip";
import { cn } from "@/lib/utils";

const HintMessage = UiSchema.TaggedEnum({ RequestedOpenTip: {}, RequestedCloseTip: {} });

export const Hint = Html.component({
  name: "Hint",
  props: Schema.Struct({
    label: Schema.String,
    name: Schema.optional(Schema.String),
    dotted: Schema.optional(Schema.Boolean),
    side: Schema.optional(Side),
    class: Schema.optional(Schema.String),
  }),
  model: Schema.Struct({ tip: Schema.Boolean }),
  message: HintMessage,
  slots: ["content"],
  restore: false,
}).make({
  init: () => ({ tip: false }),
  update: {
    RequestedOpenTip: ($) => $.evolve({ tip: true }),
    RequestedCloseTip: ($) => $.evolve({ tip: false }),
  },
  view: (h, model) =>
    Tip(h, {
      key: "tip",
      open: model.tip,
      label: h.props.label,
      side: h.props.side,
      onOpen: HintMessage.RequestedOpenTip(),
      onClose: HintMessage.RequestedCloseTip(),
      trigger: (tooltip) =>
        tooltip
          .trigger(
            h.button.attrs({
              type: "button",
              "aria-label": h.props.name,
              class: cn(
                "inline cursor-text text-left [font:inherit] [letter-spacing:inherit]",
                h.props.dotted === true && "underline decoration-dotted underline-offset-2",
                h.props.class,
              ),
            }),
          )
          .children(h.slots.content),
    }),
});
