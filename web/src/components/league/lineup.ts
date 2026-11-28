import type { View } from "@effect/ui";
import type { Html } from "@effect/ui/html";
import { UntouchableLock } from "@/components/league/untouchable";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Label, Meta } from "@/components/ui/label";
import { ListHeading } from "@/components/ui/list";
import { CardNote } from "@/components/ui/state";
import { Clickable } from "@/lib/clickable";
import { clock, startsAt } from "@/lib/times";
import type { Side, Spot, Stat } from "@/lib/types";
import { cn } from "@/lib/utils";

/** What opens a player, and whether one is yours and marked untouchable: what every list of a lineup is handed. */
type Opens<M> = {
  /** The caller's message for opening a player: the panel opens his drawer. */
  onOpen?: ((id: string) => M) | undefined;
  /** Whether you marked a player untouchable: his name carries the lock. */
  untouchable?: ((id: string) => boolean) | undefined;
};

/**
 * The team as it currently stands, and what the numbers say to change.
 *
 * Everything here is read or computed from league state, so it is on the page
 * before a report is asked for — and once one arrives it is the thing the
 * report is arguing about.
 */
export function LineupCard<M>(
  h: Html.H<M>,
  {
    title,
    lineup,
    bench,
    reserve = [],
    openSpots = 0,
    onOpen,
    untouchable,
  }: {
    title: string;
    lineup: readonly Spot[];
    bench: readonly Spot[];
    reserve?: readonly Spot[] | undefined;
    openSpots?: number | undefined;
  } & Opens<M>,
) {
  if (!lineup.length && !bench.length) return null;

  // With no opponent's kickoff to wait for, the points column is always drawn.
  const rows = { ...rowsAcross([...lineup, ...bench, ...reserve], []), started: true };
  const opens = { onOpen, untouchable };

  return Card(h).children(
    CardHeader(h).children(h.span(title), h.span(`${lineup.length} starting`)),
    h.div.class("grid grid-cols-1 md:grid-cols-2").children(
      SpotList(h, { spots: lineup, rows, ...opens }),
      h.div.class("border-t border-border md:border-l md:border-t-0").children(
        // The open spots are rows of their own below, so the heading does not count them again.
        ListHeading(h).children("Bench"),
        SpotList(h, { spots: bench, open: openSpots, rows, empty: "Nobody on the bench.", ...opens }),
        reserve.length > 0 && [ListHeading(h).children("Reserve"), SpotList(h, { spots: reserve, rows, ...opens })],
      ),
    ),
  );
}

/**
 * What every row of a lineup makes room for, whether or not it has it: the
 * points column once a game is under way, and a line of category figures once
 * anyone has one. Read from both sides of a matchup, so the two cards draw the
 * same headings, the same row heights and as many rows in each list, and slot N
 * sits beside slot N.
 */
export type Rows = {
  /** Whether any game of the week has kicked off: a player's points exist from then. */
  started: boolean;
  /** Whether any row says how it scores, so the projection and the points get columns of their own. */
  scored: boolean;
  /** The first line anyone has, whose categories head the columns; empty while nobody has one. */
  line: readonly Stat[];
  /** The most rows either side draws in each list, open spots counted on the bench: a shorter list is padded to it. */
  lineup: number;
  bench: number;
  reserve: number;
};

/** The rows' layout across every list of every side given: one side alone, or both of a matchup. */
export function rowsOf(...sides: (Side | null | undefined)[]): Rows {
  const shown = sides.filter((side): side is Side => !!side);

  return rowsAcross(
    shown.flatMap((side) => [...side.lineup, ...side.bench, ...side.reserve]),
    shown,
  );
}

function rowsAcross(spots: readonly Spot[], sides: readonly Side[]): Rows {
  const most = (count: (side: Side) => number) => Math.max(0, ...sides.map(count));

  return {
    started: spots.some((spot) => spot.scoring === "live" || spot.scoring === "final"),
    scored: spots.some((spot) => spot.scoring),
    line: spots.find((spot) => spot.line.length > 0)?.line ?? [],
    lineup: most((side) => side.lineup.length),
    bench: most((side) => side.bench.length + Math.max(side.open_spots, 0)),
    reserve: most((side) => side.reserve.length),
  };
}

/**
 * The frame every row shares, a player's or an open spot's. Its body is one
 * fixed height (`rowBody`), so a row with a game today, a kickoff, a live
 * score or a line stands exactly as tall as one with none of them.
 */
const ROW = "border-b border-border/45 px-4 py-2 last:border-b-0";

/** Name over detail (h-9), and under them a line of figures (gap-1, h-4) wherever any row has one. */
function rowBody(rows: Rows): string {
  return rows.line.length > 0 ? "h-14" : "h-9";
}

function SpotList<M>(
  h: Html.H<M>,
  {
    spots,
    rows,
    open = 0,
    pad = 0,
    empty,
    onOpen,
    untouchable,
  }: {
    spots: readonly Spot[];
    rows: Rows;
    /** Roster spots nobody holds, drawn as rows of their own after the players. */
    open?: number | undefined;
    /** Blank rows after everything else, so this list ends where the other side's does. */
    pad?: number | undefined;
    empty?: string | undefined;
  } & Opens<M>,
) {
  if (!spots.length && open <= 0 && pad <= 0) {
    return CardNote(h).children(empty ?? "Nothing set.");
  }

  const slotted = spots.some((spot) => spot.slot);

  return h.div.class("flex flex-col").children(
    spots.map((spot, i) => {
      // A place with nobody in it has nothing to open.
      const opens = spot.player_id && onOpen ? onOpen(spot.player_id) : undefined;

      return Clickable(h, "div", opens)
        .key(`${spot.player}-${i}`)
        .attrs({ "data-row": "spot", class: cn(ROW, opens !== undefined && "cursor-pointer hover:bg-muted") })
        .children(
          h.div.attr("class", cn("flex flex-col gap-1", rowBody(rows))).children(
            h.div.class("flex h-9 items-baseline gap-3").children(
              spot.slot && Label(h, { class: "w-16 shrink-0 truncate leading-5" }).children(spot.slot),
              h.div.class("min-w-0 flex-1").children(
                h.div.class("flex h-5 min-w-0 items-center gap-2").children(
                  h.span
                    .attr(
                      "class",
                      cn("truncate text-[13.5px] font-medium leading-5", spot.idle && "text-muted-foreground"),
                    )
                    .children(spot.player),
                  spot.player_id && untouchable?.(spot.player_id) === true && UntouchableLock(h, spot.player_id),
                  spot.mark && Badge(h, { variant: "info", appearance: "label", class: "shrink-0" }).children(spot.mark),
                ),
                // Drawn whether or not there is anything to say, so a row without it is no shorter.
                Meta(h, { as: "div", class: "flex h-4 min-w-0 gap-1 overflow-hidden whitespace-nowrap leading-4" }).children(
                  h.span.class("truncate").children(spot.detail),
                  // Whether he plays today, where a lineup is set day by day: never the part cut
                  // off, since it is what the day's decision turns on. Said in words; a game today
                  // is set in the foreground, a day off left muted with the rest of his row.
                  spot.today &&
                    h.span
                      .attr("class", cn("shrink-0", !spot.idle && "font-medium text-foreground"))
                      .children(`· ${spot.today}${spot.kickoff ? ` ${clock(spot.kickoff)}` : ""}`),
                  // A weekly lineup's version of the same: when his game starts, while it has not.
                  !spot.today && spot.kickoff && h.span.class("shrink-0").children(`· ${startsAt(spot.kickoff)}`),
                ),
              ),
              // His figure beside his name: a week played has the line alone, a game today the line beside his week.
              spot.scoring
                ? SpotScore(h, { spot, started: rows.started })
                : spot.tone === "warning"
                  ? Badge(h, { variant: "warn", appearance: "pill", class: "tabular-nums" }).children(spot.value)
                  : spot.value &&
                    h.span
                      .class("shrink-0 whitespace-nowrap font-mono text-[12.5px] tabular-nums")
                      .children(spot.value),
            ),
            // His line in each category on a row of its own under his name, left blank on a row
            // without one wherever another row has it, so the rows stay one height.
            rows.line.length > 0 && LineFigures(h, { line: spot.line, indent: slotted }),
          ),
        );
    }),
    // A roster spot nobody holds, as a row of its own at the foot of the bench: room to add a
    // player without dropping one. Drawn dashed and said in words, so it reads as a place
    // rather than as a player with no name, and as tall as a player's row.
    Array.from({ length: Math.max(open, 0) }, (_, i) =>
      h.div
        .key(`open-${i}`)
        .attrs({ "data-row": "open", class: ROW })
        .children(
          h.div
            .attr("class", cn("flex items-center rounded-md border border-dashed border-border px-3", rowBody(rows)))
            .children(h.span.class("truncate text-[13px] font-medium text-muted-foreground").children("Open roster spot")),
        ),
    ),
    // Room the other side's longer list takes, left blank: no border, nothing to read.
    Array.from({ length: Math.max(pad, 0) }, (_, i) =>
      h.div
        .key(`pad-${i}`)
        .attrs({ "data-row": "pad", "aria-hidden": "true", class: cn(ROW, "border-transparent") })
        .children(h.div.attr("class", rowBody(rows))),
    ),
  );
}

/** The grid a row of category figures and its heading share, so each figure sits under its label. */
function lineGrid(count: number): { gridTemplateColumns?: string } {
  return count > 0 ? { gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))` } : {};
}

/** Clears the slot label (w-16) and the gap after it, so the figures start under the name. */
const UNDER_NAME = "pl-[4.75rem]";

/**
 * His line in each category the league scores, a column each, under his
 * name: nine figures do not fit beside it, and as one sentence they truncated.
 * One line high whether he has a line or not.
 */
function LineFigures<M>(h: Html.H<M>, { line, indent }: { line: readonly Stat[]; indent: boolean }) {
  return h.div
    .attr("class", cn("grid h-4 gap-x-1 overflow-hidden font-mono text-[12px] leading-4 tabular-nums", indent && UNDER_NAME))
    .style(lineGrid(line.length))
    .children(
      line.map((figure) =>
        h.span
          .key(figure.label)
          .attrs({
            "aria-label": `${figure.label} ${figure.value}`,
            class: cn("truncate text-right", figure.value === "—" && "text-muted-foreground/50"),
          })
          .children(figure.value),
      ),
    );
}

/** The categories' names over rows that carry a line, column for column with `LineFigures`. */
function LineHeads<M, C extends View.Children<M> = []>(
  h: Html.H<M>,
  { line, indent, children, class: extra }: { line: readonly Stat[]; indent: boolean; children?: C | undefined; class?: string | undefined },
) {
  return ListHeading(h, extra).children(
    children && h.div(children),
    h.div
      .attr("class", cn("grid gap-x-1 text-right", indent && UNDER_NAME))
      .style(lineGrid(line.length))
      .children(line.map((figure) => h.span.key(figure.label).class("truncate").children(figure.label))),
  );
}

/**
 * What he was projected, then what he has scored, in two fixed columns, so
 * the real number and the guess are never one figure read two ways. Before
 * the week's first kickoff the projection is the only number and the points
 * column is not drawn at all; once any game is on, a player still to play
 * says so with a dash, and one under way leads with his points while the
 * projection steps back. Live and final are said in words, not left to a color.
 * Two lines high at most: the name and detail beside it.
 */
function SpotScore<M>(h: Html.H<M>, { spot, started }: { spot: Spot; started: boolean }) {
  const played = spot.scoring !== "projected";
  const warn = spot.tone === "warning";

  return h.div.class("flex shrink-0 items-start gap-3 text-right").children(
    h.span
      .attr(
        "class",
        cn(
          "w-14 font-mono text-[12px] leading-5 tabular-nums",
          played ? "text-muted-foreground" : warn ? "text-warn" : "text-foreground",
        ),
      )
      .children(spot.projection),
    started &&
      h.div.class("flex w-16 flex-col items-end").children(
        h.span
          .attr(
            "class",
            cn(
              "font-mono text-[14px] font-semibold leading-5 tabular-nums",
              !played ? "text-muted-foreground/50" : warn ? "text-warn" : "text-foreground",
            ),
          )
          .children(played ? spot.scored : "—"),
        played &&
          h.span
            .attr(
              "class",
              cn(
                "font-mono text-[10.5px] uppercase leading-4 tracking-wide",
                spot.scoring === "live" ? "text-ok" : "text-muted-foreground",
              ),
            )
            .children(spot.scoring === "live" ? "● live" : "final"),
      ),
  );
}

/**
 * The score columns' names over a list, flush with `SpotScore`. Chosen from
 * `rows`, not from the list under it, so both sides of a matchup draw the same heading.
 */
function ScoreHeads<M, C extends View.Children<M> = []>(
  h: Html.H<M>,
  { spots, rows, children, class: extra }: { spots: readonly Spot[]; rows: Rows; children?: C | undefined; class?: string | undefined },
) {
  if (rows.line.length > 0) {
    return LineHeads(h, { line: rows.line, indent: spots.some((spot) => spot.slot), children, class: extra });
  }

  if (!rows.scored) {
    return children ? ListHeading(h, extra).children(children) : null;
  }

  return ListHeading(h, cn("flex items-baseline gap-3", extra)).children(
    h.span.class("flex-1").children(children),
    h.span.class("w-14 text-right").children("Proj"),
    rows.started && h.span.class("w-16 text-right").children("Pts"),
  );
}

/**
 * One team in a matchup, shown beside the other.
 *
 * Both sides render identically on purpose: the question is which lineup is
 * better, and that is easier to see when nothing but the numbers differs.
 * `untouchable` is given for your side alone; `rows` says what every row
 * makes room for, from both sides (`rowsOf`), and is read from this side
 * alone where the caller does not say.
 */
export function SideCard<M>(
  h: Html.H<M>,
  {
    side,
    label,
    onOpen,
    rows,
    untouchable,
  }: { side: Side | null | undefined; label: string; rows?: Rows | undefined } & Opens<M>,
) {
  if (!side) return null;

  const layout = rows ?? rowsOf(side);
  const open = Math.max(side.open_spots, 0);
  const opens = { onOpen, untouchable };

  return Card(h).children(
    CardHeader(h).children(
      // The label is chrome and reads as such uppercased; the team name is a
      // name someone chose, and shouting it makes it harder to recognise.
      h.span
        .class("flex items-baseline gap-2")
        .children(
          label,
          h.span.class("font-sans text-[13px] font-semibold normal-case tracking-normal text-foreground").children(side.name),
        ),
      h.span
        .class("normal-case tracking-normal")
        .children([side.record, side.detail, side.points].filter(Boolean).join(" · ")),
    ),
    ScoreHeads(h, { spots: side.lineup, rows: layout, class: "border-t-0" }),
    SpotList(h, { spots: side.lineup, rows: layout, pad: layout.lineup - side.lineup.length, ...opens }),
    // Headed wherever either side has one, so the two cards' lists start level.
    layout.bench > 0 && [
      ScoreHeads(h, { spots: side.bench, rows: layout, children: ["Bench"] }),
      SpotList(h, { spots: side.bench, open, pad: layout.bench - side.bench.length - open, rows: layout, ...opens }),
    ],
    // Apart from the bench: these cost no roster spot and cannot start.
    layout.reserve > 0 && [
      ScoreHeads(h, { spots: side.reserve, rows: layout, children: ["Reserve"] }),
      SpotList(h, { spots: side.reserve, rows: layout, pad: layout.reserve - side.reserve.length, ...opens }),
    ],
  );
}
