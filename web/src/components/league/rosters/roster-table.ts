import type { View } from "@effect/ui";
import type { Html } from "@effect/ui/html";
import { UntouchableLock } from "@/components/league/untouchable";
import { Badge } from "@/components/ui/badge";
import { DataTable, type SortState } from "@/components/ui/data-table";
import { Meta } from "@/components/ui/label";
import { Hint } from "@/components/ui/overlays/hint";
import { Empty } from "@/components/ui/state";
import { toneText } from "@/lib/tone";
import type { PlayerCard } from "@/lib/types";

/** The order the server is asked for: a column and its direction, or nothing for the competition's own. */
export type Order = { readonly sort?: string; readonly descending?: boolean };

/**
 * A header's sort as the server takes it: no column is the competition's own
 * order, asked for by asking for none — the same entry as every other reader
 * of that order, such as the drawer's untouchable toggle.
 */
export function toOrder(sort: SortState | null): Order {
  return sort === null ? {} : { sort: sort.column, descending: sort.descending };
}

/**
 * A list of players, however it was arrived at.
 *
 * Your squad, somebody else's, and the wire are the same table with different
 * rows — each provider returns the same columns for all three, so the one that
 * knows how to render them is shared rather than written out per panel. The
 * few columns that are more than text say so in `roles`; none is recognised
 * by its name.
 *
 * Ordered by the server, by the one rule a page of the wire is ordered by,
 * so a column sorts alike on every table: the caller holds `sort` and asks
 * again on `onSort`, and its query keeps the rows on screen while the
 * reordered ones arrive, so a click does not blink the table out and back.
 */
export function RosterTable<M, D extends View.Children<M> = []>(
  h: Html.H<M>,
  {
    players,
    empty,
    onOpen,
    sort,
    onSort,
    detail,
    hints,
    untouchable,
  }: {
    players: PlayerCard[];
    /** Whether the manager marked a player untouchable: his name carries a lock. */
    untouchable?: ((playerId: string) => boolean) | undefined;
    /** What a column measures, by its heading, where the heading alone would mislead. */
    hints?: Record<string, string> | undefined;
    /** A line under a row, for what a caller has to say about that player. */
    detail?: ((player: PlayerCard) => D | null) | undefined;
    empty: { title: string; detail?: string | undefined };
    onOpen?: ((playerId: string) => M) | undefined;
    /** The order the server was asked for; a click asks it again. */
    sort: SortState | null;
    onSort: (next: SortState | null) => M;
  },
) {
  if (players.length === 0) return Empty(h, { title: empty.title, detail: empty.detail });

  // A column is a figure where the provider sent the number behind it: that
  // is what sorts it as one, and what aligns it like one — unless its role
  // says it reads as words, as an Opponent sorted by how soft it is does.
  const numeric = new Set(players.flatMap((p) => Object.keys(p.values).filter((column) => !p.roles[column])));

  return DataTable(h, {
    rows: players,
    numeric,
    sort,
    onSort,
    onSelect: onOpen && ((row: PlayerCard) => onOpen(row.player_id)),
    detail,
    hints,
    render: (column, value, row) => {
      const role = row.roles[column];
      // A cell that abbreviates something says it in full on hover and focus.
      const note = row.notes[column];
      // One hint per cell of the table: the row and its column name it.
      const key = `${row.player_id}:${column}`;

      // The status in the platform's own words; whether it rules him out is the provider's to say.
      if (role === "status" && value) {
        const badge = Badge(h, { variant: row.ruled_out ? "fail" : "warn", appearance: "status" }).children(value);

        if (!note) return badge;

        return Hint(h, { key, props: { label: note, name: `${value}: ${note}` }, slots: { content: badge } });
      }

      if (role === "player") {
        if (!untouchable?.(row.player_id)) return h.span.class("font-medium").children(value);

        return h.span
          .class("inline-flex items-center gap-1.5")
          .children(h.span.class("font-medium").children(value), UntouchableLock(h, row.player_id));
      }

      if (role === "slot") return Meta(h).children(value);

      // A toned cell, an Opponent against a soft defense, says so in its text too.
      const tone = row.tones[column];
      const shown = tone ? h.span.class(toneText(tone)).children(value) : value;

      if (note) return Hint(h, { key, props: { label: note, name: `${value}: ${note}`, dotted: true }, slots: { content: shown } });

      return tone ? shown : undefined;
    },
  });
}
