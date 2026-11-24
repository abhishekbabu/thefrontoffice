import type { CSSProperties, ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { CardNote } from "@/components/ui/state";
import type { Side, Spot, Stat } from "@/lib/types";
import { clickable } from "@/lib/clickable";
import { cn } from "@/lib/utils";
import { clock, startsAt } from "@/lib/times";
import { Label, Meta } from "@/components/ui/label";
import { ListHeading } from "@/components/ui/list";
import { UntouchableLock } from "@/components/league/untouchable";

/**
 * The team as it currently stands, and what the numbers say to change.
 *
 * Everything here is read or computed from league state, so it is on the page
 * before a report is asked for — and once one arrives it is the thing the
 * report is arguing about.
 */
export function LineupCard({
  title,
  lineup,
  bench,
  reserve = [],
  openSpots = 0,
  onOpen,
  untouchable,
}: {
  title: string;
  lineup: Spot[];
  bench: Spot[];
  reserve?: Spot[];
  openSpots?: number;
  onOpen?: (id: string) => void;
  /** Whether you marked a player untouchable: his name carries the lock. */
  untouchable?: (id: string) => boolean;
}) {
  if (!lineup.length && !bench.length) return null;

  // With no opponent's kickoff to wait for, the points column is always drawn.
  const rows = { ...rowsAcross([...lineup, ...bench, ...reserve], []), started: true };

  return (
    <Card>
      <CardHeader>
        <span>{title}</span>
        <span>{lineup.length} starting</span>
      </CardHeader>

      <div className="grid grid-cols-1 md:grid-cols-2">
        <SpotList spots={lineup} rows={rows} onOpen={onOpen} untouchable={untouchable} />
        <div className="border-t border-border md:border-l md:border-t-0">
          {/* The open spots are rows of their own below, so the heading does not count them again. */}
          <ListHeading>Bench</ListHeading>
          <SpotList spots={bench} open={openSpots} rows={rows} empty="Nobody on the bench." onOpen={onOpen} untouchable={untouchable} />
          {reserve.length > 0 && (
            <>
              <ListHeading>Reserve</ListHeading>
              <SpotList spots={reserve} rows={rows} onOpen={onOpen} untouchable={untouchable} />
            </>
          )}
        </div>
      </div>
    </Card>
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
  line: Stat[];
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

function rowsAcross(spots: Spot[], sides: Side[]): Rows {
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

function SpotList({
  spots,
  rows,
  open = 0,
  pad = 0,
  empty,
  onOpen,
  untouchable,
}: {
  spots: Spot[];
  rows: Rows;
  untouchable?: (id: string) => boolean;
  /** Roster spots nobody holds, drawn as rows of their own after the players. */
  open?: number;
  /** Blank rows after everything else, so this list ends where the other side's does. */
  pad?: number;
  empty?: string;
  onOpen?: (id: string) => void;
}) {
  if (!spots.length && open <= 0 && pad <= 0) {
    return <CardNote>{empty ?? "Nothing set."}</CardNote>;
  }

  const slotted = spots.some((spot) => spot.slot);

  return (
    <div className="flex flex-col">
      {spots.map((spot, i) => {
        // A place with nobody in it has nothing to open.
        const opens = spot.player_id && onOpen ? () => onOpen(spot.player_id) : undefined;

        return (
          <div
            key={`${spot.player}-${i}`}
            data-row="spot"
            {...clickable(opens)}
            className={cn(ROW, opens && "cursor-pointer hover:bg-muted")}
          >
            <div className={cn("flex flex-col gap-1", rowBody(rows))}>
              <div className="flex h-9 items-baseline gap-3">
                {spot.slot && <Label className="w-16 shrink-0 truncate leading-5">{spot.slot}</Label>}
                <div className="min-w-0 flex-1">
                  <div className="flex h-5 min-w-0 items-center gap-2">
                    <span
                      className={cn("truncate text-[13.5px] font-medium leading-5", spot.idle && "text-muted-foreground")}
                    >
                      {spot.player}
                    </span>
                    {spot.player_id && untouchable?.(spot.player_id) && <UntouchableLock />}
                    {spot.mark && (
                      <Badge variant="info" appearance="label" className="shrink-0">
                        {spot.mark}
                      </Badge>
                    )}
                  </div>
                  {/* Drawn whether or not there is anything to say, so a row without it is no shorter. */}
                  <Meta as="div" className="flex h-4 min-w-0 gap-1 overflow-hidden whitespace-nowrap leading-4">
                    <span className="truncate">{spot.detail}</span>
                    {/* Whether he plays today, where a lineup is set day by day: never the part cut
                        off, since it is what the day's decision turns on. Said in words; a game today
                        is set in the foreground, a day off left muted with the rest of his row. */}
                    {spot.today && (
                      <span className={cn("shrink-0", !spot.idle && "font-medium text-foreground")}>
                        · {spot.today}
                        {spot.kickoff && ` ${clock(spot.kickoff)}`}
                      </span>
                    )}
                    {/* A weekly lineup's version of the same: when his game starts, while it has not. */}
                    {!spot.today && spot.kickoff && <span className="shrink-0">· {startsAt(spot.kickoff)}</span>}
                  </Meta>
                </div>
                {/* His figure beside his name: a week played has the line alone, a game today the line beside his week. */}
                {spot.scoring ? (
                  <SpotScore spot={spot} started={rows.started} />
                ) : spot.tone === "warning" ? (
                  <Badge variant="warn" appearance="pill" className="tabular-nums">
                    {spot.value}
                  </Badge>
                ) : (
                  spot.value && (
                    <span className="shrink-0 whitespace-nowrap font-mono text-[12.5px] tabular-nums">{spot.value}</span>
                  )
                )}
              </div>
              {/* His line in each category on a row of its own under his name, left blank on a row
                  without one wherever another row has it, so the rows stay one height. */}
              {rows.line.length > 0 && <LineFigures line={spot.line} indent={slotted} />}
            </div>
          </div>
        );
      })}
      {/* A roster spot nobody holds, as a row of its own at the foot of the bench: room to add a
          player without dropping one. Drawn dashed and said in words, so it reads as a place
          rather than as a player with no name, and as tall as a player's row. */}
      {Array.from({ length: Math.max(open, 0) }, (_, i) => (
        <div key={`open-${i}`} data-row="open" className={ROW}>
          <div className={cn("flex items-center rounded-md border border-dashed border-border px-3", rowBody(rows))}>
            <span className="truncate text-[13px] font-medium text-muted-foreground">Open roster spot</span>
          </div>
        </div>
      ))}
      {/* Room the other side's longer list takes, left blank: no border, nothing to read. */}
      {Array.from({ length: Math.max(pad, 0) }, (_, i) => (
        <div key={`pad-${i}`} data-row="pad" aria-hidden className={cn(ROW, "border-transparent")}>
          <div className={rowBody(rows)} />
        </div>
      ))}
    </div>
  );
}

/** The grid a row of category figures and its heading share, so each figure sits under its label. */
function lineGrid(count: number): CSSProperties | undefined {
  return count > 0 ? { gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))` } : undefined;
}

/** Clears the slot label (w-16) and the gap after it, so the figures start under the name. */
const UNDER_NAME = "pl-[4.75rem]";

/**
 * His line in each category the league scores, a column each, under his
 * name: nine figures do not fit beside it, and as one sentence they truncated.
 * One line high whether he has a line or not.
 */
function LineFigures({ line, indent }: { line: Stat[]; indent: boolean }) {
  return (
    <div
      className={cn("grid h-4 gap-x-1 overflow-hidden font-mono text-[12px] leading-4 tabular-nums", indent && UNDER_NAME)}
      style={lineGrid(line.length)}
    >
      {line.map((figure) => (
        <span
          key={figure.label}
          aria-label={`${figure.label} ${figure.value}`}
          className={cn("truncate text-right", figure.value === "—" && "text-muted-foreground/50")}
        >
          {figure.value}
        </span>
      ))}
    </div>
  );
}

/** The categories' names over rows that carry a line, column for column with `LineFigures`. */
function LineHeads({
  line,
  indent,
  children,
  className,
}: {
  line: Stat[];
  indent: boolean;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <ListHeading className={className}>
      {children && <div>{children}</div>}
      <div className={cn("grid gap-x-1 text-right", indent && UNDER_NAME)} style={lineGrid(line.length)}>
        {line.map((figure) => (
          <span key={figure.label} className="truncate">
            {figure.label}
          </span>
        ))}
      </div>
    </ListHeading>
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
function SpotScore({ spot, started }: { spot: Spot; started: boolean }) {
  const played = spot.scoring !== "projected";
  const warn = spot.tone === "warning";

  return (
    <div className="flex shrink-0 items-start gap-3 text-right">
      <span
        className={cn(
          "w-14 font-mono text-[12px] leading-5 tabular-nums",
          played ? "text-muted-foreground" : warn ? "text-warn" : "text-foreground",
        )}
      >
        {spot.projection}
      </span>
      {started && (
        <div className="flex w-16 flex-col items-end">
          <span
            className={cn(
              "font-mono text-[14px] font-semibold leading-5 tabular-nums",
              !played ? "text-muted-foreground/50" : warn ? "text-warn" : "text-foreground",
            )}
          >
            {played ? spot.scored : "—"}
          </span>
          {played && (
            <span
              className={cn(
                "font-mono text-[10.5px] uppercase leading-4 tracking-wide",
                spot.scoring === "live" ? "text-ok" : "text-muted-foreground",
              )}
            >
              {spot.scoring === "live" ? "● live" : "final"}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The score columns' names over a list, flush with `SpotScore`. Chosen from
 * `rows`, not from the list under it, so both sides of a matchup draw the same heading.
 */
function ScoreHeads({
  spots,
  rows,
  children,
  className,
}: {
  spots: Spot[];
  rows: Rows;
  children?: ReactNode;
  className?: string;
}) {
  if (rows.line.length > 0) {
    return (
      <LineHeads line={rows.line} indent={spots.some((spot) => spot.slot)} className={className}>
        {children}
      </LineHeads>
    );
  }

  if (!rows.scored) {
    return children ? <ListHeading className={className}>{children}</ListHeading> : null;
  }

  return (
    <ListHeading className={cn("flex items-baseline gap-3", className)}>
      <span className="flex-1">{children}</span>
      <span className="w-14 text-right">Proj</span>
      {rows.started && <span className="w-16 text-right">Pts</span>}
    </ListHeading>
  );
}

/**
 * One team in a matchup, shown beside the other.
 *
 * Both sides render identically on purpose: the question is which lineup is
 * better, and that is easier to see when nothing but the numbers differs.
 */
export function SideCard({
  side,
  label,
  onOpen,
  rows,
  untouchable,
}: {
  side: Side | null;
  label: string;
  onOpen?: (id: string) => void;
  /** Whether you marked a player untouchable: his name carries the lock. Given for your side alone. */
  untouchable?: (id: string) => boolean;
  /** What every row makes room for, from both sides (`rowsOf`); read from this side alone where the caller does not say. */
  rows?: Rows;
}) {
  if (!side) return null;

  const layout = rows ?? rowsOf(side);
  const open = Math.max(side.open_spots, 0);

  return (
    <Card>
      <CardHeader>
        {/* The label is chrome and reads as such uppercased; the team name is a
            name someone chose, and shouting it makes it harder to recognise. */}
        <span className="flex items-baseline gap-2">
          {label}
          <span className="font-sans text-[13px] font-semibold normal-case tracking-normal text-foreground">
            {side.name}
          </span>
        </span>
        <span className="normal-case tracking-normal">{[side.record, side.detail, side.points].filter(Boolean).join(" · ")}</span>
      </CardHeader>
      <ScoreHeads spots={side.lineup} rows={layout} className="border-t-0" />
      <SpotList spots={side.lineup} rows={layout} pad={layout.lineup - side.lineup.length} onOpen={onOpen} untouchable={untouchable} />
      {/* Headed wherever either side has one, so the two cards' lists start level. */}
      {layout.bench > 0 && (
        <>
          <ScoreHeads spots={side.bench} rows={layout}>
            Bench
          </ScoreHeads>
          <SpotList
            spots={side.bench}
            open={open}
            pad={layout.bench - side.bench.length - open}
            rows={layout}
            onOpen={onOpen}
            untouchable={untouchable}
          />
        </>
      )}
      {/* Apart from the bench: these cost no roster spot and cannot start. */}
      {layout.reserve > 0 && (
        <>
          <ScoreHeads spots={side.reserve} rows={layout}>
            Reserve
          </ScoreHeads>
          <SpotList spots={side.reserve} rows={layout} pad={layout.reserve - side.reserve.length} onOpen={onOpen} untouchable={untouchable} />
        </>
      )}
    </Card>
  );
}
