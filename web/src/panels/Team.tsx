import { useQuery } from "@tanstack/react-query";
import { api, type League, type PlayerCard, type Competition, type WeekAhead } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { RosterTable } from "@/components/ui/roster-table";
import { Loading } from "@/components/ui/state";
import { usePlayerDrawer } from "@/components/ui/player";
import { ErrorNote } from "@/components/ui/error-note";
import { LeagueHeader } from "@/components/ui/page-header";

/**
 * The whole squad, in more depth than the week view.
 *
 * This is where you look at your players rather than at this week: the season
 * numbers, the ownership, the depth chart. Any row opens.
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
          <WeeksAhead competition={competition} league={league} />
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
 * Competitions that cannot look ahead return nothing, and show nothing.
 */
function WeeksAhead({ competition, league }: { competition: Competition; league: League }) {
  const weeks = useQuery<WeekAhead[], Error>({
    queryKey: ["weeks-ahead", competition.key, league.league_id],
    queryFn: () => api.weeksAhead(competition.key, league.league_id),
  });

  if (weeks.isError) return <ErrorNote error={weeks.error} />;
  if (!weeks.data?.length) return null;
  const short = weeks.data.filter((w) => w.short).length;
  return (
    <Card>
      <CardHeader>
        <span>Weeks ahead</span>
        <span>{short ? `${short} short` : `usual week ${(weeks.data[0]?.usual ?? 0).toFixed(1)}`}</span>
      </CardHeader>
      <div className="flex flex-col">
        {weeks.data.map((week) => (
          <div
            key={week.week}
            className="flex flex-col gap-1 border-t border-border px-4 py-2.5 text-[13px] first:border-t-0"
          >
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
                {week.fix} <span className="font-mono text-muted-foreground">(+{week.gain.toFixed(1)})</span>
              </p>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
