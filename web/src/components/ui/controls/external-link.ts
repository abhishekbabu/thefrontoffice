/**
 * The way across to the platform this league actually lives on.
 *
 * Reading it is what this app does; the moves are made there, so every view
 * that shows a league offers the way out to it. Always a new tab — you come
 * here to decide and go there to act, and losing the page you decided from is
 * the one thing that must not happen.
 *
 * `noreferrer` alongside `noopener`: the target has no business knowing which
 * page sent you, and `noopener` alone still leaks a referrer. What the link
 * says beside its icon is its `content` slot; with no `href` it draws nothing.
 */
import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Schema } from "effect";
import { Icon } from "@/components/ui/icon";
import { Tip } from "@/components/ui/overlays/tooltip";
import { cn } from "@/lib/utils";

const ExternalLinkMessage = UiSchema.TaggedEnum({ RequestedOpenTip: {}, RequestedCloseTip: {}, ClickedLink: {} });

export const ExternalLink = Html.component({
  name: "ExternalLink",
  props: Schema.Struct({ href: Schema.String, label: Schema.String, class: Schema.optional(Schema.String) }),
  model: Schema.Struct({ tip: Schema.Boolean }),
  message: ExternalLinkMessage,
  slots: ["content"],
  restore: false,
}).make({
  init: () => ({ tip: false }),
  update: {
    RequestedOpenTip: ($) => $.evolve({ tip: true }),
    RequestedCloseTip: ($) => $.evolve({ tip: false }),
    // Its own click, so a row the link sits in does not open as well.
    ClickedLink: ($) => $.model,
  },
  view: (h, model) =>
    // A view draws something: with no address, an empty box that takes no room.
    h.props.href === ""
      ? h.span.class("contents")
      : Tip(h, {
          key: "tip",
          open: model.tip,
          label: h.props.label,
          onOpen: ExternalLinkMessage.RequestedOpenTip(),
          onClose: ExternalLinkMessage.RequestedCloseTip(),
          trigger: (tooltip) =>
            tooltip
              .trigger(
                h.a.attrs({
                  href: h.props.href,
                  target: "_blank",
                  rel: "noopener noreferrer",
                  "aria-label": h.props.label,
                  class: cn(
                    "inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-[13px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground motion-reduce:transition-none",
                    h.props.class,
                  ),
                }),
              )
              .on("click", ExternalLinkMessage.ClickedLink())
              .children(h.slots.content, Icon(h, "external-link", { class: "size-3.5 shrink-0" })),
        }),
});
