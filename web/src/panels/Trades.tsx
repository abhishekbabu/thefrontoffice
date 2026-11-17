import { useQuery } from "@tanstack/react-query";
import { api, type Competition, type League, type LeagueSchedule, type TradeIdea } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ListCard, ListRow } from "@/components/ui/list";
import { percent, percentPoints, signed } from "@/lib/format";
import { CardNote } from "@/components/ui/state";
import { StatStrip } from "@/components/ui/stat";
import { keys } from "@/lib/queries";
import { LeagueHeader } from "@/components/ui/page-header";

/** The deadline's label in the league's headline, which this page shows on its own. */
const DEADLINE = "Trade deadline";

/**
 * The trades worth offering, under the league's trade deadline.
 *
 * The deadline is the league schedule's own figure — the one the Schedule
 * page's header and its marked week show — read from the same cached answer,
 * so the three cannot say different weeks.
 */
export function TradesPanel({ competition, league }: { competition: Competition; league: League }) {
  const schedule = useQuery<LeagueSchedule, Error>({
    queryKey: keys.schedule(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).schedule,
  });
  const deadline = (schedule.data?.headline ?? []).filter((stat) => stat.label === DEADLINE);
  return (
    <>
      <LeagueHeader league={league} />
      <StatStrip stats={deadline} />
      <div className="flex flex-col gap-4 p-5">
        <TradeIdeas competition={competition} league={league} />
      </div>
    </>
  );
}

/**
 * The trades that would do most for you, with who to offer each to and why he might say yes.
 *
 * Beside the weeks ahead because a trade is a roster move like a pickup, and
 * often the fix for a short week no free agent closes. Fetched apart from the
 * squad: each one is a season played out thousands of times, which is seconds
 * the roster should not wait on.
 *
 * Two figures for you, because a trade does two things: what it does to your
 * playoff chance, and what it does to your lineup once you are there. The
 * badge is the second where the playoff weeks are projected, since a team that
 * is in needs December more than another point of chance.
 *
 * Under each, the players whose own games price them off their projection,
 * and why: a trade resting on a role that just changed should say so.
 */
function TradeIdeas({ competition, league }: { competition: Competition; league: League }) {
  const trades = useQuery<TradeIdea[], Error>({
    queryKey: keys.trades(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).trades,
  });

  return (
    <ListCard
      title="Trades worth offering"
      count={trades.data ? `${trades.data.length} found` : undefined}
      loading={trades.isLoading}
      error={trades.error}
    >
      {trades.data?.length === 0 && (
        <CardNote>No trade worth offering right now.</CardNote>
      )}
      {trades.data?.map((idea) => (
        <ListRow key={`${idea.team_id}-${idea.giving.join()}-${idea.receiving.join()}`}>
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="truncate">
              Give {idea.giving.join(" and ")} for {idea.receiving.join(", ")}
            </span>
            <span className="truncate font-mono text-[11px] text-muted-foreground">
              with {idea.team} ({theirCase(idea)}) · your playoffs {percentPoints(idea.playoffs_change)}, to{" "}
              {percent(idea.playoffs)}
              {idea.playoff_points != null && <> · rest of season {signed(idea.points)} a week</>}
            </span>
            {idea.pickup && (
              <span className="truncate font-mono text-[11px] text-muted-foreground">
                frees a spot: add {idea.pickup}
              </span>
            )}
            {/* Why a price is not the projection: wrapped, since the reason is the point. */}
            {idea.form.map((line) => (
              <span key={line.label} className="text-[11px] leading-snug text-muted-foreground">
                <span className="text-foreground/80">{line.label}</span> {line.value}
              </span>
            ))}
          </span>
          {/* The figure that matters most, said in words as well as tinted. */}
          <Badge variant="ok" appearance="pill" className="shrink-0 tabular-nums">
            {idea.playoff_points != null
              ? `${signed(idea.playoff_points)} a playoff week`
              : `${signed(idea.points)} a week`}
          </Badge>
        </ListRow>
      ))}
    </ListCard>
  );
}

/**
 * Why the other manager might say yes: out of the race he weighs only worth,
 * and in it, his starters.
 */
export function theirCase(idea: TradeIdea): string {
  if (idea.their_playoffs < 0.05) return `out of the race, ${percent(idea.their_playoffs)}`;
  return `their starters ${signed(idea.their_points)} a week`;
}
