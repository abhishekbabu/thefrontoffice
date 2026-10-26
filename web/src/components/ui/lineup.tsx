import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { CardNote } from "@/components/ui/state";
import type { Side, Spot, Swap } from "@/lib/api";
import { cn } from "@/lib/utils";

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
          <div className="border-b border-border px-4 py-2 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            Bench
          </div>
          <SpotList spots={bench} empty="Nobody on the bench." onOpen={onOpen} />
        </div>
      </div>

      {swaps.length > 0 && (
        <div className="border-t border-border">
          <div className="px-4 pb-1 pt-3 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            Changes the projections imply
          </div>
          {/* Exact, not suggested: the report's job is to endorse or overrule
              these, not to discover them. */}
          {swaps.map((swap) => (
            <div key={swap.start} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-2 text-[13px]">
              <span className="font-medium">{swap.start}</span>
              <span className="text-muted-foreground">for {swap.out || "an empty place"}</span>
              <span className="ml-auto font-mono text-[12px] text-ok">{swap.gain}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
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
          onClick={open}
          onKeyDown={open && ((e) => e.key === "Enter" && open())}
          tabIndex={open ? 0 : undefined}
          role={open ? "button" : undefined}
          className={cn(
            "flex items-baseline gap-3 border-b border-border/45 px-4 py-2 last:border-b-0",
            open && "cursor-pointer hover:bg-muted",
          )}
        >
          {spot.slot && (
            <span className="w-16 shrink-0 font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              {spot.slot}
            </span>
          )}
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13.5px] font-medium">{spot.player}</div>
            <div className="truncate font-mono text-[11px] text-muted-foreground">{spot.detail}</div>
          </div>
          {spot.tone === "warning" ? (
            <Badge variant="warn" appearance="pill" className="tabular-nums">
              {spot.value}
            </Badge>
          ) : (
            <span className={cn("shrink-0 font-mono text-[12.5px] tabular-nums")}>{spot.value}</span>
          )}
        </div>
        );
      })}
    </div>
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
      <SpotList spots={side.lineup} onOpen={onOpen} />
      {side.bench.length > 0 && (
        <>
          <div className="border-y border-border px-4 py-2 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            Bench
          </div>
          <SpotList spots={side.bench} onOpen={onOpen} />
        </>
      )}
    </Card>
  );
}
