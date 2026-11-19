import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { CardNote } from "@/components/ui/state";
import type { Side, Spot, Swap } from "@/lib/api";
import { clickable } from "@/lib/clickable";
import { cn } from "@/lib/utils";
import { Label, Meta } from "@/components/ui/label";
import { ListHeading } from "@/components/ui/list";

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
  swaps,
  onOpen,
}: {
  title: string;
  lineup: Spot[];
  bench: Spot[];
  reserve?: Spot[];
  openSpots?: number;
  swaps: Swap[];
  onOpen?: (id: string) => void;
}) {
  if (!lineup.length && !bench.length) return null;
  return (
    <Card>
      <CardHeader>
        <span>{title}</span>
        <span>{lineup.length} starting</span>
      </CardHeader>

      <div className="grid grid-cols-1 md:grid-cols-2">
        <SpotList spots={lineup} onOpen={onOpen} />
        <div className="border-t border-border md:border-l md:border-t-0">
          {/* The open spots are rows of their own below, so the heading does not count them again. */}
          <ListHeading>Bench</ListHeading>
          {(bench.length > 0 || openSpots === 0) && (
            <SpotList spots={bench} empty="Nobody on the bench." onOpen={onOpen} />
          )}
          <OpenSpots count={openSpots} />
          {reserve.length > 0 && (
            <>
              <ListHeading>Reserve</ListHeading>
              <SpotList spots={reserve} onOpen={onOpen} />
            </>
          )}
        </div>
      </div>

      {swaps.length > 0 && <Swaps swaps={swaps} className="border-t border-border" />}
    </Card>
  );
}

/**
 * Changes the projections imply — exact, not suggested: a report's job is to
 * endorse or overrule these, not to discover them.
 */
export function Swaps({ swaps, className }: { swaps: Swap[]; className?: string }) {
  return (
    <div className={className}>
      <ListHeading>Projected swaps</ListHeading>
      {swaps.map((swap) => (
        <div key={swap.start} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-2 text-[13px]">
          <span className="font-medium">{swap.start}</span>
          <span className="text-muted-foreground">for {swap.out || "empty slot"}</span>
          <span className="ml-auto font-mono text-[12px] text-ok">{swap.gain}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * A roster spot nobody holds, as a row of its own at the foot of the bench:
 * room to add a player without dropping one. Drawn dashed and said in words,
 * so it reads as a place rather than as a player with no name.
 */
function OpenSpots({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <div className="flex flex-col gap-1.5 px-4 py-2">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="rounded-md border border-dashed border-border px-3 py-1.5">
          <div className="text-[13px] font-medium text-muted-foreground">Open roster spot</div>
        </div>
      ))}
    </div>
  );
}

function SpotList({
  spots,
  empty,
  onOpen,
  started = true,
}: {
  spots: Spot[];
  empty?: string;
  onOpen?: (id: string) => void;
  /** Whether any game of the week has kicked off: before then there are no points to give a column. */
  started?: boolean;
}) {
  if (!spots.length) {
    return <CardNote>{empty ?? "Nothing set."}</CardNote>;
  }
  return (
    <div className="flex flex-col">
      {spots.map((spot, i) => {
        // A place with nobody in it has nothing to open.
        const open = spot.player_id && onOpen ? () => onOpen(spot.player_id) : undefined;
        return (
        <div
          key={`${spot.player}-${i}`}
          {...clickable(open)}
          className={cn(
            "flex items-baseline gap-3 border-b border-border/45 px-4 py-2 last:border-b-0",
            open && "cursor-pointer hover:bg-muted",
          )}
        >
          {spot.slot && (
            <Label className="w-16 shrink-0">{spot.slot}</Label>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate text-[13.5px] font-medium">{spot.player}</span>
              {spot.mark && (
                <Badge variant="info" appearance="label" className="shrink-0">
                  {spot.mark}
                </Badge>
              )}
            </div>
            <Meta as="div" className="truncate">{spot.detail}</Meta>
          </div>
          {spot.scoring ? (
            <SpotScore spot={spot} started={started} />
          ) : spot.tone === "warning" ? (
            <Badge variant="warn" appearance="pill" className="tabular-nums">
              {spot.value}
            </Badge>
          ) : (
            <span className="shrink-0 font-mono text-[12.5px] tabular-nums">{spot.value}</span>
          )}
        </div>
        );
      })}
    </div>
  );
}

/**
 * What he was projected, then what he has scored, in two fixed columns, so
 * the real number and the guess are never one figure read two ways. Before
 * the week's first kickoff the projection is the only number and the points
 * column is not drawn at all; once any game is on, a player still to play
 * says so with a dash, and one under way leads with his points while the
 * projection steps back. Live and final are said in words, not left to a color.
 */
function SpotScore({ spot, started }: { spot: Spot; started: boolean }) {
  const played = spot.scoring !== "projected";
  const warn = spot.tone === "warning";
  return (
    <div className="flex shrink-0 items-start gap-3 text-right">
      <span
        className={cn(
          "w-14 font-mono text-[12px] tabular-nums",
          played ? "text-muted-foreground" : warn ? "text-warn" : "text-foreground",
        )}
      >
        {spot.projection}
      </span>
      {started && (
        <div className="flex w-16 flex-col items-end gap-0.5">
          <span
            className={cn(
              "font-mono text-[14px] font-semibold tabular-nums",
              !played ? "text-muted-foreground/50" : warn ? "text-warn" : "text-foreground",
            )}
          >
            {played ? spot.scored : "—"}
          </span>
          {played && (
            <span
              className={cn(
                "font-mono text-[10.5px] uppercase tracking-wide",
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

/** Whether any game of the week has kicked off, on any of `sides`: a player's points exist from then. */
export function underWay(...sides: (Side | null | undefined)[]): boolean {
  return sides.some((side) =>
    [...(side?.lineup ?? []), ...(side?.bench ?? []), ...(side?.reserve ?? [])].some(
      (spot) => spot.scoring === "live" || spot.scoring === "final",
    ),
  );
}

/** The score columns' names, set over rows that carry them, flush with `SpotScore`. */
function ScoreHeads({
  spots,
  started,
  children,
  className,
}: {
  spots: Spot[];
  started: boolean;
  children?: ReactNode;
  className?: string;
}) {
  if (!spots.some((spot) => spot.scoring)) {
    return children ? <ListHeading className={className}>{children}</ListHeading> : null;
  }
  return (
    <ListHeading className={cn("flex items-baseline gap-3", className)}>
      <span className="flex-1">{children}</span>
      <span className="w-14 text-right">Proj</span>
      {started && <span className="w-16 text-right">Pts</span>}
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
  started,
}: {
  side: Side | null;
  label: string;
  onOpen?: (id: string) => void;
  /** Whether the week's first game has kicked off; read from this side alone where the caller does not say. */
  started?: boolean;
}) {
  if (!side) return null;
  const on = started ?? underWay(side);
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
        <span className="normal-case tracking-normal">{[side.detail, side.points].filter(Boolean).join(" · ")}</span>
      </CardHeader>
      <ScoreHeads spots={side.lineup} started={on} className="border-t-0" />
      <SpotList spots={side.lineup} onOpen={onOpen} started={on} />
      {(side.bench.length > 0 || side.open_spots > 0) && (
        <>
          <ScoreHeads spots={side.bench} started={on}>
            Bench
          </ScoreHeads>
          {side.bench.length > 0 && <SpotList spots={side.bench} onOpen={onOpen} started={on} />}
          <OpenSpots count={side.open_spots} />
        </>
      )}
      {/* Apart from the bench: these cost no roster spot and cannot start. */}
      {side.reserve.length > 0 && (
        <>
          <ScoreHeads spots={side.reserve} started={on}>
            Reserve
          </ScoreHeads>
          <SpotList spots={side.reserve} onOpen={onOpen} started={on} />
        </>
      )}
    </Card>
  );
}
