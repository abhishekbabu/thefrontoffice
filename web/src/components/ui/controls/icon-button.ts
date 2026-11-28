/**
 * An icon control that always carries its name.
 *
 * The label is required, not optional: an icon alone is a guess, and the two
 * places it has to appear — a tooltip for a mouse, an accessible name for a
 * screen reader and for keyboard focus — are the same string. Taking one
 * argument makes it impossible to supply one and forget the other.
 */
import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Schema } from "effect";
import { buttonVariants } from "@/components/ui/controls/button";
import { Icon } from "@/components/ui/icon";
import { IconName } from "@/components/ui/icons";
import { Side, Tip } from "@/components/ui/overlays/tooltip";
import { cn } from "@/lib/utils";

export const IconButtonProps = Schema.Struct({
  label: Schema.String,
  icon: IconName,
  /** Classes on the icon itself: a refresh's spin while it runs. */
  iconClass: Schema.optional(Schema.String),
  side: Schema.optional(Side),
  variant: Schema.optional(Schema.Literals(["primary", "secondary", "ghost", "outline"])),
  class: Schema.optional(Schema.String),
  disabled: Schema.optional(Schema.Boolean),
  /** `aria-expanded`, for a control that opens something. */
  expanded: Schema.optional(Schema.Boolean),
  /** `aria-controls`: the id of what it opens. */
  controls: Schema.optional(Schema.String),
  /** `aria-pressed`, for a control that toggles. */
  pressed: Schema.optional(Schema.Boolean),
});

export type IconButtonProps = typeof IconButtonProps.Type;

/** `Clicked`: the button was pressed. The parent decides what that does. */
export const IconButtonEvents = UiSchema.TaggedEnum({ Clicked: {} });

const IconButtonMessage = UiSchema.TaggedEnum({
  RequestedOpenTip: {},
  RequestedCloseTip: {},
  ClickedButton: {},
});

const flag = (value: boolean | undefined) => (value === undefined ? undefined : String(value));

export const IconButton = Html.component({
  name: "IconButton",
  props: IconButtonProps,
  model: Schema.Struct({ tip: Schema.Boolean }),
  message: IconButtonMessage,
  events: IconButtonEvents,
  restore: false,
}).make({
  init: () => ({ tip: false }),
  update: {
    RequestedOpenTip: ($) => $.evolve({ tip: true }),
    RequestedCloseTip: ($) => $.evolve({ tip: false }),
    ClickedButton: ($) => $.emit(IconButtonEvents.Clicked()),
  },
  view: (h, model) => {
    const { label, icon, side, variant, disabled, expanded, controls, pressed } = h.props;

    return Tip(h, {
      key: "tip",
      open: model.tip,
      label,
      side,
      onOpen: IconButtonMessage.RequestedOpenTip(),
      onClose: IconButtonMessage.RequestedCloseTip(),
      trigger: (tooltip) =>
        tooltip
          .trigger(
            h.button
              .attrs({
                type: "button",
                "aria-label": label,
                "aria-expanded": flag(expanded),
                "aria-controls": controls,
                "aria-pressed": flag(pressed),
                class: cn(buttonVariants({ variant: variant ?? "ghost", size: "icon" }), h.props.class),
              })
              .disabled(disabled === true),
          )
          .on("click", IconButtonMessage.ClickedButton())
          .on("keydown", () => undefined)
          .children(Icon(h, icon, { class: h.props.iconClass })),
    });
  },
});
