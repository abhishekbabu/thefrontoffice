/**
 * A table whose columns come from the data.
 *
 * Every competition names its own — FPL sends Price and xGI, football sends Depth —
 * so a client that hard-codes columns has to learn each competition. This reads the
 * keys off the first row and renders whatever arrives, which is also what
 * makes adding a competition a backend change alone.
 */
import { Component, Mount, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import type { View } from "@effect/ui";
import { Effect, Schema } from "effect";
import { Icon } from "@/components/ui/icon";
import { Hint } from "@/components/ui/overlays/hint";
import { Side, Tip } from "@/components/ui/overlays/tooltip";
import { Table, Td, Th } from "@/components/ui/table";
import { Clickable } from "@/lib/clickable";
import { pressableRow } from "@/lib/motion/press";
import { cn } from "@/lib/utils";

export const SortState = Schema.Struct({ column: Schema.String, descending: Schema.Boolean });

export type SortState = typeof SortState.Type;

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
 * after it uses that answer. Held as percentages, so the table still follows
 * its container without being measured again — and with the width they
 * summed to as its floor, so on a phone the table scrolls inside its card
 * rather than squeezing every column to a letter.
 *
 * Measured once per table element, which is keyed by its columns: a different
 * competition or league gets a new one, a sort never does.
 */
const FreezeWidths = Mount.make("FreezeWidths", {}, (table: HTMLTableElement) =>
  Effect.sync(() => {
    const cells = [...(table.tHead?.rows[0]?.cells ?? [])];
    const sizes = cells.map((cell) => cell.getBoundingClientRect().width);
    const total = sizes.reduce((sum, size) => sum + size, 0);

    if (!total) return;

    cells.forEach((cell, i) => {
      cell.style.width = `${(((sizes[i] ?? 0) / total) * 100).toFixed(3)}%`;
    });

    table.style.tableLayout = "fixed";

    table.style.minWidth = `${Math.ceil(total)}px`;
  }).pipe(Effect.as(Component.noop)),
);

const SortHeaderMessage = UiSchema.TaggedEnum({ RequestedOpenTip: {}, RequestedCloseTip: {}, ClickedHeader: {} });

/** `Clicked`: the heading was pressed, to sort by it, reverse it, or clear it. */
const SortHeaderEvents = UiSchema.TaggedEnum({ Clicked: {} });

/**
 * A heading that sorts: its label says which of the three states the next
 * click is, which is not guessable from an arrow. Through the shared tooltip
 * rather than `title`, so it is styled, prompt, and reachable by keyboard.
 */
const SortHeader = Html.component({
  name: "SortHeader",
  props: Schema.Struct({
    column: Schema.String,
    label: Schema.String,
    side: Side,
    active: Schema.Boolean,
    descending: Schema.Boolean,
    numeric: Schema.Boolean,
    dense: Schema.Boolean,
  }),
  model: Schema.Struct({ tip: Schema.Boolean }),
  message: SortHeaderMessage,
  events: SortHeaderEvents,
  restore: false,
}).make({
  init: () => ({ tip: false }),
  update: {
    RequestedOpenTip: ($) => $.evolve({ tip: true }),
    RequestedCloseTip: ($) => $.evolve({ tip: false }),
    ClickedHeader: ($) => $.emit(SortHeaderEvents.Clicked()),
  },
  view: (h, model) => {
    const { column, label, side, active, descending, numeric, dense } = h.props;

    return Tip(h, {
      key: "tip",
      open: model.tip,
      label,
      side,
      onOpen: SortHeaderMessage.RequestedOpenTip(),
      onClose: SortHeaderMessage.RequestedCloseTip(),
      trigger: (tooltip) =>
        tooltip
          .trigger(
            h.button.attrs({
              type: "button",
              "aria-label": label,
              // px-4 to match a cell's, so a heading sits over its column
              // rather than four pixels inside it. Reversed in a figures
              // column so the label stays flush with the digits under it
              // and the arrow's reserved space falls on the far side.
              class: cn(
                "flex w-full items-center gap-1 py-2 transition-colors hover:text-foreground motion-reduce:transition-none",
                dense ? "px-2" : "px-4",
                numeric && "flex-row-reverse justify-start",
                active && "text-foreground",
              ),
            }),
          )
          .on("click", SortHeaderMessage.ClickedHeader())
          .children(
            // Dense headers are a category's few letters: kept whole, so the browser sizes the column to them.
            h.span.attr("class", cn(!dense && "truncate") || undefined).children(column),
            // Only the sorted column shows an arrow — one on every header is
            // decoration, one here answers "what am I looking at". The space
            // is kept on all of them regardless, or sorting a column widens it
            // by the width of an arrow.
            h.span
              .attrs({ class: "size-3 shrink-0", "aria-hidden": "true" })
              .children(active && Icon(h, descending ? "arrow-down" : "arrow-up", { class: "size-3" })),
          ),
    });
  },
});

type Row = { player_id: string; columns: Record<string, string> };

export function DataTable<M, R extends Row, D extends View.Children<M> = [], C extends View.Input<M> = string>(
  h: Html.H<M>,
  {
    rows,
    numeric,
    render,
    onSelect,
    sort = null,
    onSort,
    detail,
    hints = {},
  }: {
    rows: R[];
    /** What a column measures, by its heading, where the heading alone would mislead: said on hover. */
    hints?: Record<string, string> | undefined;
    /**
     * A full-width line under a row, where there is one. For a note about the
     * row that a cell is too narrow to hold — the model's call on a player —
     * kept beside the row it is about rather than in a list of its own.
     */
    detail?: ((row: R) => D | null) | undefined;
    /** Columns whose values are figures, so they align right like numbers. */
    numeric?: Set<string> | undefined;
    /** Per-column rendering, for the few that are more than text; `undefined` draws the value as it is. */
    render?: ((column: string, value: string, row: R) => C | undefined) | undefined;
    onSelect?: ((row: R) => M) | undefined;
    /** The column currently ordering the rows, where anything is. */
    sort?: SortState | null | undefined;
    /**
     * The message for a header clicked, with null where the click cleared the
     * sort. Its presence is what makes the table sortable. Callers ask the
     * server, which holds the one ordering rule — and on a page of four
     * thousand is the only correct answer, since sorting fifty rows of a
     * ranking answers a different question than sorting the ranking.
     */
    onSort?: ((next: SortState | null) => M) | undefined;
  },
) {
  const columns = rows[0] ? Object.keys(rows[0].columns) : [];
  const isNumeric = (column: string) => numeric?.has(column) ?? false;
  const isActive = (column: string) => sort?.column === column;
  // A league scoring nine categories sends fifteen columns: at the usual padding they truncate.
  const dense = columns.length > 10;

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
    const hint = hints[column] ? `${hints[column]}. ` : "";

    if (!isActive(column)) return `${hint}Sort by ${column}, highest first`;

    return hint + (sort?.descending ? `Sort by ${column}, lowest first` : `Clear sorting by ${column}`);
  };

  const heading = (column: string) => {
    if (onSort)
      return SortHeader(h, {
        key: column,
        props: {
          column,
          label: sortLabel(column),
          side: isNumeric(column) ? "left" : "right",
          active: isActive(column),
          descending: sort?.descending ?? false,
          numeric: isNumeric(column),
          dense,
        },
        onEmit: { Clicked: () => onSort(nextSort(column)) },
      });

    const hint = hints[column];

    if (hint)
      return Hint(h, {
        key: column,
        props: { label: hint, side: isNumeric(column) ? "left" : "right" },
        slots: { content: column },
      });

    return column;
  };

  return Table(h)
    .key(columns.join("|"))
    .onMount(FreezeWidths({}))
    .children(
      h.thead.children(
        h.tr.children(
          columns.map((column) =>
            Th(h, cn(isNumeric(column) && "text-right", dense && "px-2", onSort && "p-0"))
              .key(column)
              .children(heading(column)),
          ),
        ),
      ),
      h.tbody.children(
        rows.flatMap((row) => {
          const note = detail?.(row) ?? null;

          return [
            Clickable(h, "tr", onSelect && onSelect(row), { role: null })
              .key(row.player_id)
              .attr(
                "class",
                cn(
                  "animate-list-item transition-colors duration-150 hover:bg-muted motion-reduce:transition-none",
                  onSelect && ["cursor-pointer", pressableRow],
                ),
              )
              .children(
                columns.map((column) => {
                  const value = row.columns[column] ?? "";

                  // A row with a note under it ends at the note, not here: a rule
                  // between them reads as two rows rather than one and its note.
                  return Td(
                    h,
                    cn("truncate", dense && "px-2", isNumeric(column) && "text-right", note !== null && "border-b-0 pb-1.5"),
                  )
                    .key(column)
                    .children(render?.(column, value, row) ?? value);
                }),
              ),
            note !== null &&
              h.tr
                .key(`${row.player_id}-detail`)
                .children(
                  h.td
                    .attrs({ colspan: String(columns.length), class: "border-b border-border/45 px-4 pb-3 pt-0" })
                    .children(note),
                ),
          ];
        }),
      ),
    );
}
