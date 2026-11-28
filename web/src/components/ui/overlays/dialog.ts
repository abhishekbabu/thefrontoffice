/**
 * A panel over the page from its right edge, which the rest of the page waits behind.
 *
 * A dialog in every sense a reader can tell: announced as one and as modal,
 * focus moved into it on open and kept there, Escape and a click on the
 * backdrop both close it, and focus goes back to whatever opened it — so a
 * keyboard user lands on the row they came from rather than at the top of
 * the page. The kit's `Dialog` does all of it, in the browser's top layer, so
 * no transformed page around it can stop it at the page's width.
 *
 * Drawn whether or not it is open — `open` false is the closed state, not a
 * reason to leave it out — so it slides out as it closes rather than
 * vanishing: the kit holds it on screen until the slide ends.
 */
import { Schema } from "effect";
import type { View } from "@effect/ui";
import type { Html } from "@effect/ui/html";
import { Dialog } from "@effect/ui-kit";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Icon } from "@/components/ui/icon";
import { cn } from "@/lib/utils";

/**
 * How a drawer arrives and leaves relative to another one.
 *
 * `null` when it is the only one: it crosses from the screen's edge. When it
 * replaces another (a player opened from a move, and Back to the move), the
 * page behind has not changed, so it should not dim and lighten again: the new
 * drawer fades in a step to the side, `forward` from the right and `back` from
 * the left, and the one it replaced fades the other way.
 */
export const Swap = Schema.NullOr(Schema.Literals(["forward", "back"]));

export type Swap = typeof Swap.Type;

/**
 * The slide: in from the edge on a spring's settle, out across it gathering
 * speed — the arriving ease front-loads the move, which out of a resting
 * drawer put 40% of the screen into the first frame and read as a jump. A
 * swap travels a step instead, and fades.
 */
const SLIDE =
  "transition-[translate,opacity] duration-[240ms] ease-[cubic-bezier(0.22,1,0.36,1)] data-starting-style:translate-x-full data-ending-style:translate-x-full data-ending-style:duration-200 data-ending-style:ease-[cubic-bezier(0.4,0,0.7,0.2)]";

const SWAP = {
  forward:
    "transition-[translate,opacity] duration-[180ms] ease-[cubic-bezier(0.22,1,0.36,1)] data-starting-style:translate-x-4 data-starting-style:opacity-0 data-ending-style:-translate-x-4 data-ending-style:opacity-0 data-ending-style:duration-[140ms]",
  back: "transition-[translate,opacity] duration-[180ms] ease-[cubic-bezier(0.22,1,0.36,1)] data-starting-style:-translate-x-4 data-starting-style:opacity-0 data-ending-style:translate-x-4 data-ending-style:opacity-0 data-ending-style:duration-[140ms]",
} as const;

/**
 * The dimmed page behind a drawer. Already there when a drawer replaces
 * another, and gone at once from the one it replaced, so the page keeps one
 * shade throughout instead of two layers of it crossing.
 */
const DIM =
  "transition-opacity duration-[180ms] ease-[cubic-bezier(0.22,1,0.36,1)] data-starting-style:opacity-0 data-ending-style:opacity-0";

export function SlideOver<M, C extends View.Children<M>>(
  h: Html.H<M>,
  {
    key,
    open,
    onClose,
    label,
    swap = null,
    class: extra,
    children,
  }: {
    /** Tells two drawers of one view apart. */
    key: string;
    open: boolean;
    onClose: M;
    /** The dialog's accessible name: what it is about. */
    label: string;
    swap?: Swap;
    class?: string | undefined;
    children: C;
  },
) {
  return Dialog(h, {
    key,
    props: { open },
    onEmit: { RequestedOpen: () => undefined, RequestedClose: () => onClose, Settled: () => undefined },
    view: (dialog) =>
      h.div.class("contents").children(
        dialog.portal(h.dialog.attr("aria-label", label))?.children(
          dialog.backdrop(h.div.attr("class", cn("fixed inset-0 z-50 bg-scrim", swap === null && DIM))),
          dialog
            .viewport(h.div.class("pointer-events-none fixed inset-0 z-50 flex justify-end"))
            .children(
              dialog
                .popup(
                  h.div.attr(
                    "class",
                    cn(
                      "pointer-events-auto relative flex h-full w-full flex-col overflow-y-auto bg-popover shadow-lg outline-none",
                      swap === null ? SLIDE : SWAP[swap],
                      extra,
                    ),
                  ),
                )
                .attr("data-drawer", "")
                .children(children),
            ),
        ),
      ),
  });
}

/**
 * Where a drawer was opened from, to return to. One drawer shows at a time:
 * opening a player from a move swaps the move out, and this brings it back.
 */
export type Back<M> = { label: string; onBack: M };

/** "← Trade · A ↔ B": the drawer this one replaced, above its title. */
export function BackLink<M>(h: Html.H<M>, back: Back<M> | undefined) {
  if (back === undefined) return null;

  return h.button
    .attrs({
      type: "button",
      class: "mb-1 flex max-w-full items-center gap-1 font-mono text-[11px] text-muted-foreground hover:text-foreground",
    })
    .on("click", back.onBack)
    .on("keydown", () => undefined)
    .children(Icon(h, "chevron-left", { class: "size-3.5 shrink-0" }), h.span.class("truncate").children(back.label));
}

/**
 * A slide-over's pinned top: what it is about, a line under that, its own
 * controls, and the way out. Shared by every drawer that is not a player's.
 */
export function SlideOverHeader<M, T extends View.Children<M>, C extends View.Children<M> = []>(
  h: Html.H<M>,
  {
    title,
    meta,
    back,
    onClose,
    children,
  }: { title: T; meta?: string | undefined; back?: Back<M> | undefined; onClose: M; children?: C },
) {
  return h.div
    .class("sticky top-0 z-10 flex items-start gap-4 border-b border-border bg-popover px-5 py-4")
    .children(
      h.div
        .class("min-w-0 flex-1")
        .children(
          BackLink(h, back),
          h.h2.class("font-display text-[20px] font-semibold leading-tight tracking-tight").children(title),
          meta && h.p.class("mt-0.5 font-mono text-[12px] text-muted-foreground").children(meta),
        ),
      children,
      IconButton(h, {
        key: "close",
        props: { label: "Close", side: "left", icon: "x" },
        onEmit: { Clicked: () => onClose },
      }),
    );
}
