/**
 * One row of the to-do list, and the table of the players a move swaps: how
 * an item reads, apart from what can be done about it (`actions.ts`).
 */
import type { View } from "@effect/ui";
import type { Html } from "@effect/ui/html";
import { Badge } from "@/components/ui/badge";
import { Meta } from "@/components/ui/label";
import { Hint } from "@/components/ui/overlays/hint";
import { Linked } from "@/components/ui/stat";
import { Table, Td, Th } from "@/components/ui/table";
import { Clickable } from "@/lib/clickable";
import { pressableRow } from "@/lib/motion/press";
import { toneText, type Variant } from "@/lib/tone";
import type { Action, MovePlayer, Pickup, Stat } from "@/lib/types";
import { cn } from "@/lib/utils";

/** What an add is for, in the corner beside its deadline. */
const PICKUP: Record<Pickup, string> = {
  streamer: "Streamer",
  keeper: "Keeper",
};

/** The name a row morphs under: unique on the page, and a CSS identifier whatever the item's key holds. */
export const rowName = (prefix: string, key: string) => `${prefix}-${key.replace(/[^\w-]/g, "_")}`;

/**
 * One item: its urgency, what to do and why, the evidence, and the players it
 * swaps. `open` is the caller's message for a click on it; `children` sit
 * under it, outside what a click opens, and `detail` inside, under its reason.
 * Named for the view transition that closes it up as it leaves the list.
 */
export function Row<M, C extends View.Children<M> = [], D extends View.Children<M> = []>(
  h: Html.H<M>,
  {
    key,
    badge,
    title,
    reason,
    when,
    pickup = null,
    chance = null,
    evidence = [],
    players = [],
    detail,
    open,
    children,
  }: {
    key: string;
    badge: { label: string; variant: Variant };
    title: string;
    reason: string;
    when: string;
    /** For an add, whether he streams this week or is kept for the season. */
    pickup?: Pickup | null | undefined;
    /** What the move does to the chance of winning, where it was simulated. */
    chance?: Stat | null | undefined;
    evidence?: Action["evidence"] | undefined;
    /** Who the move brings in and takes out, compared figure by figure; empty where it moves one player. */
    players?: MovePlayer[] | undefined;
    /** Inside the row, under its reason: the best trade on offer. */
    detail?: D | undefined;
    open?: M | undefined;
    children?: C | undefined;
  },
) {
  // The badge's width, shared with the indent that lines a row's verdict up under its title.
  return h.li
    .key(key)
    .class("border-t border-border [--badge-column:5.5rem] [view-transition-class:row] first:border-t-0")
    .style({ viewTransitionName: rowName("row", key) })
    .children(
      Clickable(h, "div", open)
        .attr(
          "class",
          cn(
            "flex flex-col items-start gap-1.5 px-4 py-3 sm:flex-row sm:gap-3",
            open !== undefined && ["cursor-pointer hover:bg-muted", pressableRow],
          ),
        )
        .children(
          // Over the title on a phone: as a column of its own it took a quarter of the width.
          Badge(h, { variant: badge.variant, appearance: "status", class: "mt-0.5 shrink-0 sm:w-(--badge-column)" }).children(
            badge.label,
          ),
          // Beside the title on a wide screen; under it on a phone, where a
          // corner column squeezes the title to a word a line.
          h.div.class("grid w-full min-w-0 flex-1 grid-cols-1 sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-x-3").children(
            h.div.class("text-[13.5px] font-medium").children(title),
            (when || chance || pickup) &&
              Meta(h, {
                class:
                  "flex flex-wrap gap-x-2 pt-0.5 sm:row-span-2 sm:max-w-[11rem] sm:flex-col sm:flex-nowrap sm:items-end sm:gap-0.5 sm:text-right",
              }).children(
                // The sign is in the words; the color only lets a cost be found at a glance.
                chance && h.span.attr("class", cn("font-semibold", toneText(chance.tone))).children(chance.value),
                pickup && h.span.class("font-medium text-foreground").children(PICKUP[pickup]),
                when,
              ),
            h.div.class("min-w-0 sm:col-start-1").children(
              h.div.class("mt-0.5 text-[12.5px] text-muted-foreground").children(reason),
              players.length > 1 && Compared(h, { key, players }),
              evidence.length > 0 &&
                h.ul.class("mt-1.5 flex flex-col gap-1").children(
                  evidence.map((line, i) =>
                    h.li
                      .key(`${line.label}-${i}`)
                      .class("flex items-baseline gap-2 text-[12px] text-muted-foreground")
                      .children(
                        // The rank is in the words; the dot only lets a
                        // soft or tough matchup be found at a glance.
                        h.span.attrs({
                          "aria-hidden": "true",
                          class: cn(
                            "size-1.5 shrink-0 -translate-y-px rounded-full bg-border",
                            line.tone === "good" && "bg-ok",
                            line.tone === "warning" && "bg-warn",
                          ),
                        }),
                        h.span(
                          h.span.class("font-medium text-foreground").children(line.label),
                          " ",
                          Linked(h, { url: line.url, children: [line.value] }),
                        ),
                      ),
                  ),
                ),
              detail && h.div.class("mt-1.5").children(detail),
            ),
          ),
        ),
      // Outside the clickable area: a verdict or a thread is read, not opened.
      children && h.div.class("px-4 pb-3 sm:pl-[calc(var(--badge-column)+1.75rem)]").children(children),
    );
}

/**
 * The players a move swaps, side by side: one column each, one row per figure.
 *
 * The server sends every player the same rows in the same order, so a row
 * is read across rather than two sentences being read and held in the head.
 * In and out are said in words over each column; a tone colors only a
 * figure whose words already say what it means — an easy matchup, a status.
 * `key` tells one row's table from another's, whose explained labels are
 * children of the same list.
 */
export function Compared<M>(h: Html.H<M>, { key, players }: { key: string; players: readonly MovePlayer[] }) {
  const rows = players[0]?.figures.map((figure) => figure.label) ?? [];
  // A label that is the app's own measure says what it means on hover and focus.
  const hints = Object.fromEntries((players[0]?.figures ?? []).map((figure) => [figure.label, figure.hint]));

  return Table(h, "mt-2 w-auto text-[12px]").children(
    h.thead(
      h.tr(
        Th(h, "px-0 py-1.5"),
        players.map((player) =>
          Th(h, "px-3 py-1.5 align-bottom")
            .key(`${player.side}-${player.player_id}`)
            .children(
              h.span.class("block").children(player.side === "in" ? "In" : "Out"),
              h.span
                .class("block truncate font-sans text-[12.5px] font-medium normal-case tracking-normal text-foreground")
                .children(player.name),
              h.span.class("block font-normal normal-case tracking-normal").children(player.held),
            ),
        ),
      ),
    ),
    h.tbody(
      rows.map((label, i) =>
        h.tr.key(label).children(
          Td(h, "whitespace-nowrap px-0 py-1 font-mono text-[11px] text-muted-foreground").children(
            hints[label]
              ? Hint(h, {
                  key: `${key}-${label}`,
                  props: { label: hints[label], name: `${label}: ${hints[label]}`, dotted: true },
                  slots: { content: label },
                })
              : label,
          ),
          players.map((player) => {
            const figure = player.figures[i];

            return Td(h, cn("px-3 py-1 font-mono", toneText(figure?.tone ?? "neutral", "text-foreground")))
              .key(`${player.side}-${player.player_id}`)
              .children(figure?.value ?? "—");
          }),
        ),
      ),
    ),
  );
}
