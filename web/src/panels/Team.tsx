import { useQuery } from "@tanstack/react-query";
import { api, type League, type Competition, type Outlook } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ListCard, ListRow } from "@/components/ui/list";
import { signed } from "@/lib/format";
import { Card, CardHeader } from "@/components/ui/card";
import { RosterTable, useSortedRoster } from "@/components/ui/roster-table";
import { CardNote, QueryState } from "@/components/ui/state";
import { usePlayerDrawer } from "@/components/ui/player";
import { keys } from "@/lib/queries";
import { LeagueHeader } from "@/components/ui/page-header";
import { Label } from "@/components/ui/label";

/**
 * Your roster beyond this week: the weeks coming, and the squad itself.
 *
 * This week's page is what to do before kickoff; this is what to do about the
 * roster over the weeks after — a short week to see coming — and the squad in
 * more depth than the week shows. Trades have a page of their own. Any row opens.
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
          <Card>
            <CardHeader>
              <span>Squad</span>
              <span>{roster.data.length} players</span>
            </CardHeader>

            <RosterTable
              players={roster.data}
              empty={{ title: "No players yet" }}
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
      {weeks?.length === 0 && <CardNote>No weeks left.</CardNote>}
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
