import type { View } from "@effect/ui";
import type { Html } from "@effect/ui/html";
import { Card, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/error-note";
import { Label } from "@/components/ui/label";
import { Loading } from "@/components/ui/state";
import { pressableRow } from "@/lib/motion/press";
import { Clickable } from "@/lib/clickable";
import { cn } from "@/lib/utils";

/**
 * A titled card of rows: the shape of every list the app shows inside a card.
 *
 * It was written out per panel — the league's five lists, the weeks ahead,
 * the trades, the swaps — and each copy carried the same class strings, so
 * changing the look of a row meant finding all of them. A card that fetches
 * on its own passes `loading` and `error`, and waits the same way as every
 * other: its header at once, a loading bar inside it, so the page does not
 * jump when it arrives.
 */
export function ListCard<M, C extends View.Children<M>, A extends View.Children<M> = []>(
  h: Html.H<M>,
  {
    title,
    count,
    aside,
    loading = false,
    error = null,
    children,
  }: {
    title: string;
    /** What the card holds, said in the header's right-hand corner: "3 found", "16 weeks". */
    count?: string | undefined;
    /** Anything else for that corner, in place of `count`: a control, a status. */
    aside?: A | undefined;
    loading?: boolean | undefined;
    error?: unknown;
    children?: C | undefined;
  },
) {
  return Card(h).children(
    CardHeader(h).children(h.span(title), aside ?? (count && h.span(count))),
    loading && Loading(h, { lines: 2 }),
    error !== null && error !== undefined && ErrorNote(h, { error }),
    !loading && (error === null || error === undefined) && h.div.class("flex flex-col").children(children),
  );
}

/**
 * One row of a list card, with the one that is yours marked.
 *
 * A tint alone will not do it: `muted` is a hair off the card in light mode,
 * and a reader who cannot see the hue gets no marker at all. The rule here is
 * the same as everywhere else in this app — state carried in color is also
 * carried in shape, so the row keeps a solid rule down its left edge.
 */
export function ListRow<M>(
  h: Html.H<M>,
  { current = false, class: extra, onClick }: { current?: boolean; class?: string | undefined; onClick?: M | undefined } = {},
) {
  return Clickable(h, "div", onClick).class(
    cn(
      "flex animate-list-item items-baseline gap-3 border-t border-border py-2.5 pr-4 text-[13px] first:border-t-0",
      current ? "border-l-2 border-l-foreground bg-muted pl-[calc(1rem-2px)]" : "pl-4",
      onClick !== undefined && ["cursor-pointer hover:bg-muted", pressableRow],
      extra,
    ),
  );
}

/**
 * A heading inside a card that splits its rows into runs: the playoffs from
 * the season, one kickoff from the next, the bench from the starters.
 *
 * The lineups wrote their own — one ruled above and below, one with neither,
 * one on a tint — so the same break read three ways on one page.
 */
export function ListHeading<M>(h: Html.H<M>, extra?: string) {
  return Label(h, { as: "div", class: cn("border-t border-border bg-muted px-4 py-1.5 first:border-t-0", extra) });
}
