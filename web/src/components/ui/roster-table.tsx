import { useState } from "react";
import { DataTable, type SortState } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";
import { Empty } from "@/components/ui/state";
import type { PlayerCard } from "@/lib/api";

/** Columns whose values are figures, so they align right like numbers. */
const NUMERIC = new Set([
  "Fits",
  "Win",
  "xPts",
  "Price",
  "Proj",
  "Points",
  "Form",
  "xGI",
  "Owned",
  "Depth",
  "Exp",
  "PTS",
  "REB",
  "AST",
]);

/**
 * Values that mean "look at this".
 *
 * The provider writes a status in the platform's own words — "doubtful 75%",
 * "Questionable", "OUT" — so anything non-empty is worth a badge, and the two
 * that mean definitely-not-playing get the stronger one.
 */
function statusTone(value: string): "fail" | "warn" {
  return /\b(out|suspended|injured|ir)\b/i.test(value) ? "fail" : "warn";
}

/**
 * Order a complete list in place.
 *
 * Uses the number behind a formatted column where the provider supplied one —
 * "£15.5m" sorted as text sits below "£9.0m" — and rows with nothing to sort
 * on stay last in both directions.
 */
function sortRows(players: PlayerCard[], sort: SortState | null): PlayerCard[] {
  if (!sort) return players;
  const value = (p: PlayerCard) => p.values?.[sort.column];
  const numeric = players.some((p) => value(p) !== undefined);
  const has = (p: PlayerCard) => (numeric ? value(p) !== undefined : Boolean(p.columns[sort.column]));

  const present = players.filter(has);
  const missing = players.filter((p) => !has(p));
  const direction = sort.descending ? -1 : 1;
  present.sort((a, b) =>
    numeric
      ? ((value(a) ?? 0) - (value(b) ?? 0)) * direction
      : (a.columns[sort.column] ?? "").localeCompare(b.columns[sort.column] ?? "") * direction,
  );
  return [...present, ...missing];
}

/**
 * A list of players, however it was arrived at.
 *
 * Your squad, somebody else's, and the wire are the same table with different
 * rows — each provider returns the same columns for all three, so the one that
 * knows how to render them is shared rather than written out per panel.
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
  /** Supplied by a caller that sorts server-side; omitted to sort in place. */
  sort?: SortState | null;
  onSort?: (next: SortState | null) => void;
}) {
  const [local, setLocal] = useState<SortState | null>(null);
  // A complete list sorts itself; a page of a longer one has to ask the
  // server, because reordering the rows in hand is a different answer.
  const controlled = Boolean(onSort);
  const active = controlled ? sort ?? null : local;
  const rows = controlled ? players : sortRows(players, local);

  if (players.length === 0) return <Empty title={empty.title} detail={empty.detail} />;
  return (
    <DataTable
      rows={rows}
      numeric={NUMERIC}
      sort={active}
      onSort={onSort ?? setLocal}
      onSelect={onOpen && ((row) => onOpen(row.player_id))}
      detail={detail}
      render={(column, value) =>
        column === "Status" && value ? (
          <Badge variant={statusTone(value)} appearance="status">
            {value}
          </Badge>
        ) : column === "Player" ? (
          <span className="font-medium">{value}</span>
        ) : column === "Slot" ? (
          <span className="font-mono text-[11px] text-muted-foreground">{value}</span>
        ) : undefined
      }
    />
  );
}
