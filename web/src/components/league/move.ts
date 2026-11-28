import type { Html } from "@effect/ui/html";
import { Badge } from "@/components/ui/badge";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Meta } from "@/components/ui/label";
import { ListCard, ListRow } from "@/components/ui/list";
import { SlideOver, SlideOverHeader, type Back, type Swap } from "@/components/ui/overlays/dialog";
import { MAX_COMPARED } from "@/lib/compare";
import type { ActivityRow } from "@/lib/types";

/**
 * One league move on one line: when, who, what, and "+A, -B". Read the same in
 * the league's activity and on a player's history, and opens the same drawer.
 * A move with no players in it opens nothing.
 */
export function MoveRow<M>(h: Html.H<M>, { move, onOpen }: { move: ActivityRow; onOpen?: M | undefined }) {
  return ListRow(h, { current: move.is_mine, onClick: move.moves.length ? onOpen : undefined }).children(
    Meta(h, { class: "w-16 shrink-0" }).children(move.when),
    // Gives way on a narrow screen rather than pushing the badge out of the card.
    h.span.class("w-48 min-w-0 truncate").children(move.who),
    Badge(h, { variant: "muted", appearance: "label", class: "shrink-0" }).children(move.what),
    Meta(h, { class: "min-w-0 flex-1 truncate" }).children(move.detail),
    move.bid && h.span.class("shrink-0 font-mono text-[11px] tabular-nums").children(move.bid),
  );
}

/** What a drawer opened from `move` calls it on its Back link, and how its own header is titled. */
export const moveLabel = (move: ActivityRow) => `${move.what} · ${move.who}`;

/** The players a move holds, each once: what its comparison opens with. */
export const moveIds = (move: ActivityRow) => [...new Set(move.moves.map((m) => m.player_id))].filter(Boolean);

/**
 * A move in full: who got whom, and a way to compare its players.
 *
 * A player opened from it takes its place, and his Back link returns here.
 * `move` is what it shows, kept by the caller while it slides out; `open`
 * false is the closed state.
 */
export function MoveDrawer<M>(
  h: Html.H<M>,
  {
    move,
    open,
    back,
    swap,
    onClose,
    onOpenPlayer,
    onCompare,
  }: {
    move: ActivityRow | null;
    open: boolean;
    /** The drawer this one replaced, where there was one. */
    back?: Back<M> | undefined;
    swap?: Swap | undefined;
    onClose: M;
    /** Swap to a player; the caller makes this move what his drawer goes back to. */
    onOpenPlayer: (id: string) => M;
    /** Swap to a comparison of its players, which the caller likewise makes come back here. */
    onCompare: (ids: string[]) => M;
  },
) {
  return SlideOver(h, {
    key: "move",
    open: open && move !== null,
    onClose,
    label: move ? `${move.what} by ${move.who}` : "Move",
    swap: swap ?? null,
    class: "max-w-lg border-l border-border",
    children: [move && MoveDetail(h, { move, back, onClose, onOpen: onOpenPlayer, onCompare: onCompare(moveIds(move)) })],
  });
}

function MoveDetail<M>(
  h: Html.H<M>,
  {
    move,
    back,
    onClose,
    onOpen,
    onCompare,
  }: { move: ActivityRow; back: Back<M> | undefined; onClose: M; onOpen: (id: string) => M; onCompare: M },
) {
  const players = moveIds(move).length;

  return h.div.class("contents").children(
    SlideOverHeader(h, {
      title: [moveLabel(move)],
      meta: [move.when, move.bid && `won for ${move.bid}`].filter(Boolean).join(" · "),
      back,
      onClose,
      children: [
        players > 1 &&
          IconButton(h, {
            key: "compare",
            props: {
              label: players > MAX_COMPARED ? `Compare the first ${MAX_COMPARED}` : "Compare these players",
              icon: "git-compare-arrows",
            },
            onEmit: { Clicked: () => onCompare },
          }),
      ],
    }),
    h.div.class("flex flex-col gap-4 p-5").children(
      sections(move).map(({ title, moves }) =>
        ListCard(h, {
            title,
            count: `${moves.length}`,
            children: moves.map((m) =>
              ListRow(h, { onClick: m.player_id ? onOpen(m.player_id) : undefined })
                .key(`${m.change}-${m.player_id || m.player}`)
                .children(
                  // Said, not only colored: which way he went is the whole row.
                  Badge(h, { variant: m.change === "added" ? "ok" : "fail", appearance: "label", class: "shrink-0" }).children(
                    m.change === "added" ? "+" : "−",
                  ),
                  h.span.class("min-w-0 flex-1 truncate").children(m.player),
                  Meta(h, { class: "shrink-0" }).children([m.position, m.team].filter(Boolean).join(" · ")),
                ),
            ),
        }).key(title),
      ),
    ),
  );
}

/**
 * A move's players in the sections that make it readable.
 *
 * A trade reads by who got whom — one section per manager, holding the players
 * his roster took — since "added" and "dropped" each mix both sides. Anything
 * one manager did alone reads as what he added and what he let go.
 */
export function sections(move: ActivityRow): { title: string; moves: ActivityRow["moves"] }[] {
  const managers = [...new Set(move.moves.filter((m) => m.change === "added").map((m) => m.manager))];

  if (managers.length > 1) {
    return managers.map((manager) => ({
      title: `To ${manager}`,
      moves: move.moves.filter((m) => m.change === "added" && m.manager === manager),
    }));
  }

  return [
    { title: "Added", moves: move.moves.filter((m) => m.change === "added") },
    { title: "Dropped", moves: move.moves.filter((m) => m.change === "dropped") },
  ].filter((section) => section.moves.length > 0);
}
