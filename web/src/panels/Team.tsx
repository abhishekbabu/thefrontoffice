import { useQuery } from "@tanstack/react-query";
import { api, type League, type Competition, type TradeIdea, type Outlook } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ListCard, ListRow } from "@/components/ui/list";
import { percent, percentPoints, signed } from "@/lib/format";
import { Card, CardHeader } from "@/components/ui/card";
import { RosterTable, useSortedRoster } from "@/components/ui/roster-table";
import { CardNote, QueryState } from "@/components/ui/state";
import { usePlayerDrawer } from "@/components/ui/player";
import { keys } from "@/lib/queries";
import { LeagueHeader } from "@/components/ui/page-header";
import { Label } from "@/components/ui/label";

/**
 * Your roster beyond this week: the weeks coming, the trades worth offering, and the squad itself.
 *
 * This week's page is what to do before kickoff; this is what to do about the
 * roster over the weeks after — a short week to see coming, a trade to send —
 * and the squad in more depth than the week shows. Any row opens.
 */
export function TeamPanel({ competition, league }: { competition: Competition; league: League }) {
  const { openPlayer, drawer } = usePlayerDrawer(competition, league);

  const { roster, sort, onSort } = useSortedRoster(
    keys.roster(competition.key, league.league_id),
    api.league(competition.key, league.league_id).roster,
  );

  return (
    <>
      <LeagueHeader league={league} />

      <QueryState query={roster} lines={5} />

      {roster.data && (
        <div className="flex flex-col gap-4 p-5">
          {competition.plans_weeks && <WeeksAhead competition={competition} league={league} />}
          {competition.finds_trades && <Trades competition={competition} league={league} />}
          <Card>
            <CardHeader>
              <span>Squad</span>
              <span>{roster.data.length} players</span>
            </CardHeader>

            <RosterTable
              players={roster.data}
              empty={{ title: "No players yet", detail: "This roster is empty for the current season." }}
              onOpen={openPlayer}
              sort={sort}
              onSort={onSort}
            />
          </Card>
        </div>
      )}
      {drawer}
    </>
  );
}

/**
 * The next few weeks as the roster stands.
 *
 * A week where byes and injuries land together is a loss that can be seen a
 * month out, and a pickup made then costs a bench spot rather than whatever
 * is left on the morning. Every week is shown, so a dip reads against the
 * others; one short enough to act on carries the pickup that fixes it.
 */
function WeeksAhead({ competition, league }: { competition: Competition; league: League }) {
  const outlook = useQuery<Outlook, Error>({
    queryKey: keys.weeksAhead(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).weeksAhead,
  });

  const weeks = outlook.data?.weeks;
  const short = weeks?.filter((w) => w.short).length ?? 0;
  const usual = outlook.data?.usual;
  return (
    <ListCard
      title="Weeks ahead"
      count={short ? `${short} short` : usual != null ? `usual week ${usual.toFixed(1)}` : undefined}
      loading={outlook.isLoading}
      error={outlook.error}
    >
      {weeks?.length === 0 && <CardNote>No weeks left in the season to plan.</CardNote>}
      {weeks?.map((week) => (
        <ListRow key={week.week} className="flex-col items-stretch gap-1">
          <div className="flex items-baseline gap-3">
            <Label className="w-20 shrink-0">Week {week.week}</Label>
            <span className="min-w-0 flex-1 truncate text-muted-foreground">
              {week.missing.length ? `Without ${week.missing.join(", ")}` : "Everyone available"}
            </span>
            <span className="shrink-0 font-mono text-[12px] tabular-nums">{week.points.toFixed(1)} proj</span>
            {/* Said in words as well as tinted. */}
            {week.short && (
              <Badge variant="fail" appearance="pill" className="shrink-0">
                short {week.short_by.toFixed(1)}
              </Badge>
            )}
          </div>
          {week.fix && (
            <p className="pl-[5.75rem] text-[12.5px]">
              {week.fix} <span className="font-mono text-muted-foreground">({signed(week.gain)})</span>
            </p>
          )}
        </ListRow>
      ))}
    </ListCard>
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
 */
function Trades({ competition, league }: { competition: Competition; league: League }) {
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
