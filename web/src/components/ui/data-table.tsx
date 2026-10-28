import { useLayoutEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { m } from "motion/react";
import { list, listItem } from "@/lib/motion";
import { Table, Td, Th } from "@/components/ui/table";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * A table whose columns come from the data.
 *
 * Every competition names its own — FPL sends Price and xGI, football sends Depth —
 * so a client that hard-codes columns has to learn each competition. This reads the
 * keys off the first row and renders whatever arrives, which is also what
 * makes adding a competition a backend change alone.
 */
export type SortState = { column: string; descending: boolean };

export function DataTable<Row extends { player_id: string; columns: Record<string, string> }>({
  rows,
  numeric,
  render,
  onSelect,
  sort,
  onSort,
  detail,
}: {
  rows: Row[];
  /**
   * A full-width line under a row, where there is one. For a note about the
   * row that a cell is too narrow to hold — the model's call on a player —
   * kept beside the row it is about rather than in a list of its own.
   */
  detail?: (row: Row) => React.ReactNode;
  /** Columns whose values are figures, so they align right like numbers. */
  numeric?: Set<string>;
  /** Per-column rendering, for the few that are more than text. */
  render?: (column: string, value: string, row: Row) => React.ReactNode;
  onSelect?: (row: Row) => void;
  /** The column currently ordering the rows, where anything is. */
  sort?: SortState | null;
  /**
   * Called when a header is clicked, with null where the click cleared the
   * sort. Its presence is what makes the table sortable: a caller holding the
   * whole list passes one that sorts locally, and a caller holding one page of
   * four thousand passes one that asks the server — which is the only correct
   * answer there, since sorting fifty rows of a ranking answers a different
   * question than sorting the ranking.
   */
  onSort?: (next: SortState | null) => void;
}) {
  const columns = rows[0] ? Object.keys(rows[0].columns) : [];
  const isNumeric = (column: string) => numeric?.has(column) ?? false;
  const isActive = (column: string) => sort?.column === column;

  /**
   * Column widths, measured once from the real content and then held.
   *
   * Left to itself the browser sizes a table from the cells it can see, and
   * sorting changes which cells those are — so every column shifted a little
   * and the sorted one jumped, moving whatever you meant to click next.
   *
   * A proportional rule was the obvious fix and cannot work: `Status` carries
   * a pill and `Pos` carries three letters, and no rule that knows only
   * "not a number" can give one 145px and the other 65. So the first paint is
   * measured — with the browser doing what it is good at — and every render
   * after it uses that answer. Stored as percentages, so the table still
   * follows its container without being measured again.
   *
   * Re-measured only when the columns themselves change, which is a different
   * competition or a different league, and never on a sort.
   */
  const key = columns.join("|");
  const [frozen, setFrozen] = useState<{ key: string; widths: string[] } | null>(null);
  const head = useRef<HTMLTableRowElement>(null);
  const widths = frozen?.key === key ? frozen.widths : null;

  useLayoutEffect(() => {
    if (!head.current || widths) return;
    const cells = [...head.current.children] as HTMLElement[];
    const sizes = cells.map((cell) => cell.getBoundingClientRect().width);
    const total = sizes.reduce((sum, size) => sum + size, 0);
    if (!total) return;
    setFrozen({ key, widths: sizes.map((size) => `${((size / total) * 100).toFixed(3)}%`) });
  }, [key, widths]);

  /**
   * Biggest first, then smallest, then back to the order it arrived in.
   *
   * The third click is the one that matters: the order rows come in is an
   * answer of its own — the competition's own ranking, or the lineup in the
   * order it is played — and without a way back the only route to it was to
   * leave the page and return.
   */
  const nextSort = (column: string): SortState | null => {
    if (!isActive(column)) return { column, descending: true };
    if (sort?.descending) return { column, descending: false };
    return null;
  };

  const sortLabel = (column: string) => {
    if (!isActive(column)) return `Sort by ${column}, highest first`;
    return sort?.descending ? `Sort by ${column}, lowest first` : `Clear sorting by ${column}`;
  };

  return (
    // Fixed only once the widths are known: until then the browser sizes the
    // columns from the content, which is the measurement being taken.
    <Table className={cn(widths && "table-fixed")}>
      {widths && (
        <colgroup>
          {columns.map((column, i) => (
            <col key={column} style={{ width: widths[i] }} />
          ))}
        </colgroup>
      )}
      <thead>
        <tr ref={head}>
          {columns.map((column) => (
            <Th key={column} className={cn(isNumeric(column) && "text-right", onSort && "p-0")}>
              {onSort ? (
                // The label says which of the three states the next click is,
                // which is not guessable from an arrow. Through the shared
                // tooltip rather than `title`, so it is styled, prompt, and
                // reachable by keyboard like every other one in the app.
                <Tooltip label={sortLabel(column)} side={isNumeric(column) ? "left" : "right"}>
                  <button
                  type="button"
                  onClick={() => onSort(nextSort(column))}
                  aria-label={sortLabel(column)}
                  // px-4 to match a cell's, so a heading sits over its column
                  // rather than four pixels inside it. Reversed in a figures
                  // column so the label stays flush with the digits under it
                  // and the arrow's reserved space falls on the far side.
                  className={cn(
                    "flex w-full items-center gap-1 px-4 py-2 transition-colors hover:text-foreground",
                    isNumeric(column) && "flex-row-reverse justify-start",
                    isActive(column) && "text-foreground",
                  )}
                >
                  <span className="truncate">{column}</span>
                  {/* Only the sorted column shows an arrow — one on every
                      header is decoration, one here answers "what am I looking
                      at". The space is kept on all of them regardless, or
                      sorting a column widens it by the width of an arrow. */}
                  <span className="size-3 shrink-0" aria-hidden>
                    {isActive(column) &&
                      (sort?.descending ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />)}
                  </span>
                  </button>
                </Tooltip>
              ) : (
                column
              )}
            </Th>
          ))}
        </tr>
      </thead>
      <m.tbody variants={list} initial="hidden" animate="shown">
        {rows.flatMap((row) => {
          const note = detail?.(row);
          return [
          // A motion row rather than a wrapped one: anything between <tbody>
          // and <tr> breaks the table's own layout.
          <m.tr
            key={row.player_id}
            variants={listItem}
            onClick={onSelect && (() => onSelect(row))}
            onKeyDown={onSelect && ((e: React.KeyboardEvent) => e.key === "Enter" && onSelect(row))}
            tabIndex={onSelect ? 0 : undefined}
            className={cn("hover:bg-muted", onSelect && "cursor-pointer")}
          >
            {columns.map((column) => {
              const value = row.columns[column] ?? "";
              return (
                // A row with a note under it ends at the note, not here: a rule
                // between them reads as two rows rather than one and its note.
                <Td key={column} className={cn("truncate", isNumeric(column) && "text-right", note && "border-b-0 pb-1.5")}>
                  {render?.(column, value, row) ?? value}
                </Td>
              );
            })}
          </m.tr>,
            ...(note
              ? [
                  <tr key={`${row.player_id}-detail`}>
                    <td colSpan={columns.length} className="border-b border-border/45 px-4 pb-3 pt-0">
                      {note}
                    </td>
                  </tr>,
                ]
              : []),
          ];
        })}
      </m.tbody>
    </Table>
  );
}
