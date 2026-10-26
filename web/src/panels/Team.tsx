import { useQuery } from "@tanstack/react-query";
import { api, type League, type PlayerCard, type Competition, type TradeIdea, type WeekAhead } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ListCard, ListRow } from "@/components/ui/list";
import { percent, percentPoints, signed } from "@/lib/format";
import { Card, CardHeader } from "@/components/ui/card";
import { RosterTable } from "@/components/ui/roster-table";
import { CardNote, Loading } from "@/components/ui/state";
import { usePlayerDrawer } from "@/components/ui/player";
import { ErrorNote } from "@/components/ui/error-note";
import { LeagueHeader } from "@/components/ui/page-header";

/**
 * Your roster beyond this week: the weeks coming, the trades worth offering, and the squad itself.
 *
 * This week's page is what to do before kickoff; this is what to do about the
 * roster over the weeks after — a short week to see coming, a trade to send —
 * and the squad in more depth than the week shows. Any row opens.
 */
export function TeamPanel({ competition, league }: { competition: Competition; league: League }) {
  const { openPlayer, drawer } = usePlayerDrawer(competition, league);

  const roster = useQuery<PlayerCard[], Error>({
    queryKey: ["roster", competition.key, league.league_id],
    queryFn: () => api.roster(competition.key, league.league_id),
  });

  return (
    <>
      <LeagueHeader league={league} />

      {roster.isError && <ErrorNote error={roster.error} />}
      {roster.isLoading && <Loading lines={5} />}

      {roster.data && (
        <div className="flex flex-col gap-4 p-5">
          {competition.plans_ahead && <WeeksAhead competition={competition} league={league} />}
          {competition.plans_ahead && <Trades competition={competition} league={league} />}
          <Card>
            <CardHeader>
              <span>Squad</span>
              <span>{roster.data.length} players</span>
            </CardHeader>

            <RosterTable
              players={roster.data}
              empty={{ title: "No players yet", detail: "This roster is empty for the current season." }}
              onOpen={openPlayer}
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
  const weeks = useQuery<WeekAhead[], Error>({
    queryKey: ["weeks-ahead", competition.key, league.league_id],
    queryFn: () => api.weeksAhead(competition.key, league.league_id),
  });

  const short = weeks.data?.filter((w) => w.short).length ?? 0;
  const usual = weeks.data?.[0]?.usual;
  return (
    <ListCard
      title="Weeks ahead"
      count={short ? `${short} short` : usual !== undefined ? `usual week ${usual.toFixed(1)}` : undefined}
      loading={weeks.isLoading}
      error={weeks.error}
    >
      {weeks.data?.length === 0 && <CardNote>No weeks left in the season to plan.</CardNote>}
      {weeks.data?.map((week) => (
        <ListRow key={week.week} className="flex-col items-stretch gap-1">
          <div className="flex items-baseline gap-3">
            <span className="w-20 shrink-0 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
              Week {week.week}
            </span>
            <span className="min-w-0 flex-1 truncate text-muted-foreground">
              {week.missing.length ? `Without ${week.missing.join(", ")}` : "Everyone available"}
            </span>
            <span className="shrink-0 font-mono text-[12px] tabular-nums">{week.points.toFixed(1)} proj</span>
            {/* Said in words as well as tinted. */}
            {week.short && (
              <Badge variant="fail" appearance="pill" className="shrink-0">
                short {(week.usual - week.points).toFixed(1)}
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
 * The trades that would most raise your playoff chance, and help the other side's starters too.
 *
 * Beside the weeks ahead because a trade is a roster move like a pickup, and
 * often the fix for a short week no free agent closes. Fetched apart from the
 * squad: each one is a season played out thousands of times, which is seconds
 * the roster should not wait on.
 */
function Trades({ competition, league }: { competition: Competition; league: League }) {
  const trades = useQuery<TradeIdea[], Error>({
    queryKey: ["trades", competition.key, league.league_id],
    queryFn: () => api.trades(competition.key, league.league_id),
  });

  return (
    <ListCard
      title="Trades worth offering"
      count={trades.data ? `${trades.data.length} found` : undefined}
      loading={trades.isLoading}
      error={trades.error}
    >
      {trades.data?.length === 0 && (
        <CardNote>
          No one-for-one swap improves both starting lineups and raises your playoff chance by half a point or
          more. Trading is closed after the deadline.
        </CardNote>
      )}
      {trades.data?.map((idea) => (
        <ListRow key={`${idea.team_id}-${idea.giving.join()}-${idea.receiving.join()}`}>
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="truncate">
              Give {idea.giving.join(", ")} for {idea.receiving.join(", ")}
            </span>
            <span className="truncate font-mono text-[11px] text-muted-foreground">
              with {idea.team} · your starters {signed(idea.points)} a week, theirs {signed(idea.their_points)}
              {" · "}their playoffs {percentPoints(idea.their_playoffs_change)}
            </span>
          </span>
          {/* The figure the list is ranked on, said in words as well as tinted. */}
          <Badge variant="ok" appearance="pill" className="shrink-0 tabular-nums">
            {percentPoints(idea.playoffs_change)} · {percent(idea.playoffs)} playoffs
          </Badge>
        </ListRow>
      ))}
    </ListCard>
  );
}
