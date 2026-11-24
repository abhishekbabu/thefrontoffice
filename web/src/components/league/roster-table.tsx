import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { DataTable, type SortState } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";
import { Empty } from "@/components/ui/state";
import { Hint } from "@/components/ui/overlays/tooltip";
import { Meta } from "@/components/ui/label";
import { toneText } from "@/lib/tone";
import type { PlayerCard, PlayerOrder } from "@/lib/types";
import { UntouchableLock } from "@/components/league/untouchable";

/** A header's sort as the server takes it: no column is the competition's own order. */
export function toOrder(sort: SortState | null): PlayerOrder {
  return { sort: sort?.column ?? "", descending: sort?.descending ?? true };
}

/**
 * A whole roster, ordered by whichever column was last clicked.
 *
 * Ordered by the server, by the one rule a page of the wire is ordered by,
 * so a column sorts alike on every table. Keeps the rows on screen while the
 * reordered ones arrive, so a click does not blink the table out and back.
 */
export function useSortedRoster(key: readonly unknown[], fetch: (order: PlayerOrder) => Promise<PlayerCard[]>, enabled = true) {
  const [sort, setSort] = useState<SortState | null>(null);

  const roster = useQuery<PlayerCard[], Error>({
    queryKey: [...key, sort],
    queryFn: () => fetch(toOrder(sort)),
    placeholderData: keepPreviousData,
    enabled,
  });

  return { roster, sort, onSort: setSort };
}

/**
 * A list of players, however it was arrived at.
 *
 * Your squad, somebody else's, and the wire are the same table with different
 * rows — each provider returns the same columns for all three, so the one that
 * knows how to render them is shared rather than written out per panel. The
 * few columns that are more than text say so in `roles`; none is recognised
 * by its name.
 */
export function RosterTable({
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
  untouchable?: (playerId: string) => boolean;
  /** What a column measures, by its heading, where the heading alone would mislead. */
  hints?: Record<string, string>;
  /** A line under a row, for what a caller has to say about that player. */
  detail?: (player: PlayerCard) => React.ReactNode;
  empty: { title: string; detail?: string };
  onOpen?: (playerId: string) => void;
  /** The order the server was asked for; a click asks it again. */
  sort: SortState | null;
  onSort: (next: SortState | null) => void;
}) {
  if (players.length === 0) return <Empty title={empty.title} detail={empty.detail} />;

  // A column is a figure where the provider sent the number behind it: that
  // is what sorts it as one, and what aligns it like one — unless its role
  // says it reads as words, as an Opponent sorted by how soft it is does.
  const numeric = new Set(players.flatMap((p) => Object.keys(p.values).filter((column) => !p.roles[column])));

  return (
    <DataTable
      rows={players}
      numeric={numeric}
      sort={sort}
      onSort={onSort}
      onSelect={onOpen && ((row) => onOpen(row.player_id))}
      detail={detail}
      hints={hints}
      render={(column, value, row) => {
        const role = row.roles[column];
        // A cell that abbreviates something says it in full on hover and focus.
        const note = row.notes[column];

        // The status in the platform's own words; whether it rules him out is the provider's to say.
        if (role === "status" && value) {
          const badge = (
            <Badge variant={row.ruled_out ? "fail" : "warn"} appearance="status">
              {value}
            </Badge>
          );

          if (!note) return badge;

          return (
            <Hint label={note} name={`${value}: ${note}`}>
              {badge}
            </Hint>
          );
        }

        if (role === "player") {
          if (!untouchable?.(row.player_id)) return <span className="font-medium">{value}</span>;

          return (
            <span className="inline-flex items-center gap-1.5">
              <span className="font-medium">{value}</span>
              <UntouchableLock />
            </span>
          );
        }

        if (role === "slot") return <Meta>{value}</Meta>;

        // A toned cell, an Opponent against a soft defense, says so in its text too.
        const tone = row.tones[column];
        const shown = tone ? <span className={toneText(tone)}>{value}</span> : value;

        if (note) {
          return (
            <Hint label={note} name={`${value}: ${note}`} dotted>
              {shown}
            </Hint>
          );
        }

        return tone ? shown : undefined;
      }}
    />
  );
}
