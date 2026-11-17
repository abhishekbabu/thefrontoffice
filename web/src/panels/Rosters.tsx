import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, type League, type Competition, type Outlook, type TeamRef } from "@/lib/api";
import { ToggleChip } from "@/components/ui/toggle";
import { ExternalLink } from "@/components/ui/external-link";
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
 * Any roster in the league: yours by default, anyone's from the chips.
 *
 * The weeks coming and the squad itself, in the same columns for every team,
 * so another manager's short week reads as plainly as yours. Trades have a
 * page of their own. Any row opens. The team shown is in the address
 * (`?team=4`), so a roster opened from the league table can be linked.
 */
export function RostersPanel({ competition, league }: { competition: Competition; league: League }) {
  const { openPlayer, drawer } = usePlayerDrawer(competition, league);
  const leagueApi = api.league(competition.key, league.league_id);
  const [params, setParams] = useSearchParams();

  const teams = useQuery<TeamRef[], Error>({
    queryKey: keys.teams(competition.key, league.league_id),
    queryFn: leagueApi.teams,
  });
  const asked = params.get("team");
  const selected = teams.data?.find((t) => t.team_id === asked) ?? teams.data?.find((t) => t.is_mine);
  // Yours is read as yours — the columns that say how a player fits your lineup
  // — and anybody else's as theirs.
  const yours = !selected || selected.is_mine;

  const mine = useSortedRoster(keys.roster(competition.key, league.league_id), leagueApi.roster, yours);
  const theirs = useSortedRoster(
    keys.teamRoster(competition.key, league.league_id, selected?.team_id),
    (order) => leagueApi.teamRoster(selected!.team_id, order),
    !yours,
  );
  const { roster, sort, onSort } = yours ? mine : theirs;
  const pick = (team: TeamRef) =>
    setParams((p) => {
      if (team.is_mine) p.delete("team");
      else p.set("team", team.team_id);
      return p;
    });

  return (
    <>
      <LeagueHeader league={league} />
      {(teams.data?.length ?? 0) > 1 && (
        <div className="flex flex-wrap gap-1.5 px-5 pt-5">
          {teams.data!.map((t) => (
            <ToggleChip key={t.team_id} pressed={t.team_id === selected?.team_id} onClick={() => pick(t)}>
              <span className="max-w-[14rem] truncate">{t.name}</span>
              {t.is_mine && (
                <span className="font-mono text-[10px] uppercase tracking-[0.08em] opacity-70">you</span>
              )}
            </ToggleChip>
          ))}
        </div>
      )}

      <QueryState query={roster} lines={5} />

      {roster.data && (
        <div className="flex flex-col gap-4 p-5">
          {competition.plans_weeks && (
            <WeeksAhead competition={competition} league={league} team={yours ? "" : selected!.team_id} />
          )}
          <Card>
            <CardHeader>
              <span className="flex items-center gap-1">
                {selected?.name ?? "Squad"}
                {selected && !yours && (
                  <ExternalLink href={selected.url} label={`Open ${selected.name} on the platform`} />
                )}
              </span>
              <span>{[selected?.detail, `${roster.data.length} players`].filter(Boolean).join(" · ")}</span>
            </CardHeader>

            <RosterTable
              players={roster.data}
              empty={{ title: "No players" }}
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
function WeeksAhead({ competition, league, team }: { competition: Competition; league: League; team: string }) {
  const outlook = useQuery<Outlook, Error>({
    queryKey: keys.weeksAhead(competition.key, league.league_id, team),
    queryFn: () => api.league(competition.key, league.league_id).weeksAhead(team),
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
