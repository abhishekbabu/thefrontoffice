import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { CardNote } from "@/components/ui/state";
import type { Side, Spot, Swap } from "@/lib/api";
import { clickable } from "@/lib/clickable";
import { cn } from "@/lib/utils";
import { Label } from "@/components/ui/label";

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
  swaps,
  onOpen,
}: {
  title: string;
  lineup: Spot[];
  bench: Spot[];
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
          <Label as="div" className="border-b border-border px-4 py-2">
            Bench
          </Label>
          <SpotList spots={bench} empty="Nobody on the bench." onOpen={onOpen} />
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
      <Label as="div" className="px-4 pb-1 pt-3">
        Changes the projections imply
      </Label>
      {swaps.map((swap) => (
        <div key={swap.start} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-2 text-[13px]">
          <span className="font-medium">{swap.start}</span>
          <span className="text-muted-foreground">for {swap.out || "an empty place"}</span>
          <span className="ml-auto font-mono text-[12px] text-ok">{swap.gain}</span>
        </div>
      ))}
    </div>
  );
}

function SpotList({ spots, empty, onOpen }: { spots: Spot[]; empty?: string; onOpen?: (id: string) => void }) {
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
            <div className="truncate text-[13.5px] font-medium">{spot.player}</div>
            <div className="truncate font-mono text-[11px] text-muted-foreground">{spot.detail}</div>
          </div>
          {spot.scoring ? (
            <SpotScore spot={spot} />
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
 * What he has scored beside what he was projected, in two fixed columns, so
 * the real number and the guess are never one figure read two ways. Before
 * kickoff the projection is the only number, and the points column says so
 * with a dash; once the game is on the points lead and the projection steps
 * back. Live and final are said in words, not left to a color.
 */
function SpotScore({ spot }: { spot: Spot }) {
  const played = spot.scoring !== "projected";
  const warn = spot.tone === "warning";
  return (
    <div className="flex shrink-0 items-start gap-3 text-right">
      <div className="flex w-14 flex-col items-end gap-0.5">
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
              "font-mono text-[9.5px] uppercase tracking-wider",
              spot.scoring === "live" ? "text-ok" : "text-muted-foreground",
            )}
          >
            {spot.scoring === "live" ? "● live" : "final"}
          </span>
        )}
      </div>
      <span
        className={cn(
          "w-12 font-mono text-[12px] tabular-nums",
          played ? "text-muted-foreground" : warn ? "text-warn" : "text-foreground",
        )}
      >
        {spot.projection}
      </span>
    </div>
  );
}

/** The two score columns' names, set over rows that carry them, flush with `SpotScore`. */
function ScoreHeads({ spots, children, className }: { spots: Spot[]; children?: ReactNode; className?: string }) {
  if (!spots.some((spot) => spot.scoring)) {
    return children ? (
      <Label as="div" className={cn("border-y border-border px-4 py-2", className)}>
        {children}
      </Label>
    ) : null;
  }
  return (
    <Label as="div" className={cn("flex items-baseline gap-3 border-y border-border px-4 py-2", className)}>
      <span className="flex-1">{children}</span>
      <span className="w-14 text-right">Pts</span>
      <span className="w-12 text-right">Proj</span>
    </Label>
  );
}

/**
 * One team in a matchup, shown beside the other.
 *
 * Both sides render identically on purpose: the question is which lineup is
 * better, and that is easier to see when nothing but the numbers differs.
 */
export function SideCard({ side, label, onOpen }: { side: Side | null; label: string; onOpen?: (id: string) => void }) {
  if (!side) return null;
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
      <ScoreHeads spots={side.lineup} className="border-t-0" />
      <SpotList spots={side.lineup} onOpen={onOpen} />
      {side.bench.length > 0 && (
        <>
          <ScoreHeads spots={side.bench}>Bench</ScoreHeads>
          <SpotList spots={side.bench} onOpen={onOpen} />
        </>
      )}
    </Card>
  );
}
