/** The rail's items: one look for everything in it, whether it navigates or not. */
import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Schema } from "effect";
import { Tip } from "@/components/ui/overlays/tooltip";
import { pressable } from "@/lib/motion/press";
import { cn } from "@/lib/utils";

export function railItem(active: boolean, disabled: boolean, extra?: string) {
  return cn(
    "flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[13.5px]",
    pressable,
    active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-muted",
    disabled && "cursor-not-allowed opacity-40 hover:bg-transparent",
    extra,
  );
}

const RailBlockedMessage = UiSchema.TaggedEnum({ RequestedOpenTip: {}, RequestedCloseTip: {} });

/**
 * A rail item that goes nowhere — a competition you cannot play — and why, on
 * hover and on focus. Disabled by `aria-disabled` rather than `disabled`: a
 * disabled control cannot be hovered in every browser, nor reached by
 * keyboard, and the reason is the point of it. What it says is its slot.
 */
export const RailBlocked = Html.component({
  name: "RailBlocked",
  props: Schema.Struct({ reason: Schema.String }),
  model: Schema.Struct({ tip: Schema.Boolean }),
  message: RailBlockedMessage,
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
      label: h.props.reason,
      side: "right",
      onOpen: RailBlockedMessage.RequestedOpenTip(),
      onClose: RailBlockedMessage.RequestedCloseTip(),
      trigger: (tooltip) =>
        tooltip
          .trigger(h.button.attrs({ type: "button", "aria-disabled": "true", class: railItem(false, true) }))
          .children(h.slots.content),
    }),
});
