import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { DataTable, type SortState } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";
import { Empty } from "@/components/ui/state";
import type { PlayerCard, PlayerOrder } from "@/lib/api";

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
}: {
  players: PlayerCard[];
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
  // is what sorts it as one, and what aligns it like one.
  const numeric = new Set(players.flatMap((p) => Object.keys(p.values)));
  return (
    <DataTable
      rows={players}
      numeric={numeric}
      sort={sort}
      onSort={onSort}
      onSelect={onOpen && ((row) => onOpen(row.player_id))}
      detail={detail}
      render={(column, value, row) => {
        const role = row.roles[column];
        // The status in the platform's own words; whether it rules him out is the provider's to say.
        if (role === "status" && value) {
          return (
            <Badge variant={row.ruled_out ? "fail" : "warn"} appearance="status">
              {value}
            </Badge>
          );
        }
        if (role === "player") return <span className="font-medium">{value}</span>;
        if (role === "slot") return <span className="font-mono text-[11px] text-muted-foreground">{value}</span>;
        return undefined;
      }}
    />
  );
}
