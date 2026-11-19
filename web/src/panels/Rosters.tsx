import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, type League, type Competition, type Outlook, type TeamRef } from "@/lib/api";
import { Table, Td, Th } from "@/components/ui/table";
import { clickable } from "@/lib/clickable";
import { ToggleChip, ToggleGroup } from "@/components/ui/toggle";
import { ExternalLink } from "@/components/ui/external-link";
import { Badge } from "@/components/ui/badge";
import { ListCard, ListRow } from "@/components/ui/list";
import { signed } from "@/lib/format";
import { Card, CardHeader } from "@/components/ui/card";
import { RosterTable, useSortedRoster } from "@/components/ui/roster-table";
import { CardNote, QueryState } from "@/components/ui/state";
import { useDrawers } from "@/components/ui/drawers";
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
  const { openPlayer, drawer } = useDrawers(competition, league);
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
          <ToggleGroup>
            {teams.data!.map((t) => (
              <ToggleChip key={t.team_id} pressed={t.team_id === selected?.team_id} onClick={() => pick(t)}>
                <span className="max-w-[14rem] truncate">{t.name}</span>
                {t.is_mine && (
                  <span className="font-mono text-[10px] uppercase tracking-[0.08em] opacity-70">you</span>
                )}
              </ToggleChip>
            ))}
          </ToggleGroup>
        </div>
      )}

      <QueryState query={roster} lines={5} />

      {roster.data && (
        <div className="flex flex-col gap-4 p-5">
          {competition.plans_weeks && (
            <WeeksAhead
              competition={competition}
              league={league}
              team={yours ? "" : selected!.team_id}
              onOpen={openPlayer}
            />
          )}
          <Card>
            <CardHeader>
              <span className="flex items-center gap-1">
                {selected?.name ?? "Squad"}
                {selected && !yours && (
                  <ExternalLink href={selected.url} label={`Open ${selected.name} on the platform`} />
                )}
              </span>
              <span>{roster.data.length} players</span>
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
 * is left on the morning. Only a week with something to say is listed —
 * somebody missing, a regular with few games, a heavy week, one short enough
 * to act on — with the pickup that fixes it where one does; a stretch with
 * nothing to say is one line, not a row a week saying so. A week the league
 * has yet to finish scheduling is provisional: its count is a floor. A week
 * counts projected points, or in basketball the games the daily lineups can start.
 */
function WeeksAhead({
  competition,
  league,
  team,
  onOpen,
}: {
  competition: Competition;
  league: League;
  team: string;
  onOpen: (id: string) => void;
}) {
  const outlook = useQuery<Outlook, Error>({
    queryKey: keys.weeksAhead(competition.key, league.league_id, team),
    queryFn: () => api.league(competition.key, league.league_id).weeksAhead(team),
  });
  // A competition that reads its weeks ahead as fixtures — FPL — sends a grid instead of weeks.
  if (outlook.data && outlook.data.run_weeks.length > 0) {
    const runs = outlook.data.runs;
    return (
      <ListCard title="Weeks ahead" count={runs.length ? `${runs.length} to watch` : undefined}>
        <FixtureGrid outlook={outlook.data} onOpen={onOpen} />
      </ListCard>
    );
  }

  const weeks = outlook.data?.weeks;
  const flagged = weeks?.filter(
    (w) => w.missing.length > 0 || w.light.length > 0 || w.short || w.heavy || w.provisional || w.fix,
  );
  const short = weeks?.filter((w) => w.short).length ?? 0;
  const usual = outlook.data?.usual;
  const games = outlook.data?.measure === "games";
  // Games are whole; a usual week of them is a median, which can fall between two.
  const figure = (value: number) => (games ? `${Number(value.toFixed(1))} games` : `${value.toFixed(1)} proj`);
  return (
    <ListCard
      title="Weeks ahead"
      count={short ? `${short} short` : usual != null ? `usual week ${figure(usual)}` : undefined}
      loading={outlook.isLoading}
      error={outlook.error}
    >
      {weeks?.length === 0 && <CardNote>No weeks left.</CardNote>}
      {weeks && weeks.length > 0 && flagged?.length === 0 && (
        <CardNote>Nothing to flag through week {weeks[weeks.length - 1]!.week}.</CardNote>
      )}
      {flagged?.map((week) => (
        <ListRow key={week.week} className="flex-col items-stretch gap-1">
          <div className="flex items-baseline gap-3">
            <Label className="w-20 shrink-0">Week {week.week}</Label>
            <span className="min-w-0 flex-1 truncate text-muted-foreground">
              {week.missing.length ? `Without ${week.missing.join(", ")}` : "Everyone available"}
            </span>
            <span className="shrink-0 font-mono text-[12px] tabular-nums">{figure(week.points)}</span>
            {/* Said in words as well as tinted. */}
            {week.provisional && (
              <Badge variant="warn" appearance="pill" className="shrink-0">
                provisional
              </Badge>
            )}
            {week.heavy && (
              <Badge variant="ok" appearance="pill" className="shrink-0">
                heavy
              </Badge>
            )}
            {week.short && (
              <Badge variant="fail" appearance="pill" className="shrink-0">
                short {Number(week.short_by.toFixed(1))}
              </Badge>
            )}
          </div>
          {week.light.length > 0 && (
            <p className="pl-[5.75rem] text-[12.5px] text-muted-foreground">Light: {week.light.join(", ")}</p>
          )}
          {week.fix && (
            <p className="pl-[5.75rem] text-[12.5px]">
              {week.fix}{" "}
              <span className="font-mono text-muted-foreground">
                ({games ? `${signed(week.gain, 0)} games` : signed(week.gain)})
              </span>
            </p>
          )}
        </ListRow>
      ))}
    </ListCard>
  );
}

/** FPL's 1-5 fixture difficulty as a badge's tone; the number is printed too, so it is not color alone. */
function difficultyTone(difficulty: number): "ok" | "muted" | "warn" | "fail" {
  return difficulty <= 2 ? "ok" : difficulty === 3 ? "muted" : difficulty === 4 ? "warn" : "fail";
}

/**
 * Each listed player's next gameweeks, a column a week: opponent, home or away,
 * and difficulty. Only a player with something to act on gets a row — a blank,
 * a double, a hard run, a doubt — and the weeks a blank or double lands on the
 * squad are named above; everybody else is one line.
 */
function FixtureGrid({ outlook, onOpen }: { outlook: Outlook; onOpen: (id: string) => void }) {
  const weeks = outlook.run_weeks;
  const last = weeks[weeks.length - 1];
  return (
    <>
      {outlook.warnings.map((w) => (
        <ListRow key={`${w.label}-${w.value}`} className="items-baseline gap-3">
          <Label className="w-20 shrink-0">{w.label}</Label>
          <span className={w.tone === "warning" ? "text-warn" : w.tone === "good" ? "text-ok" : undefined}>
            {w.value}
          </span>
        </ListRow>
      ))}
      {outlook.runs.length > 0 && (
        <Table>
          <thead>
            <tr>
              <Th>Player</Th>
              {weeks.map((week) => (
                <Th key={week} className="px-2 text-center">
                  GW{week}
                </Th>
              ))}
            </tr>
          </thead>
          <tbody>
            {outlook.runs.map((run) => (
              <tr
                key={run.player_id}
                className="cursor-pointer hover:bg-muted/50"
                {...clickable(() => onOpen(run.player_id), { role: null })}
              >
                <Td>
                  <div className="font-medium">{run.player}</div>
                  <div className="text-[11.5px] text-muted-foreground">
                    {run.detail} · {run.flags.join(" · ")}
                  </div>
                </Td>
                {run.weeks.map((week) => (
                  <Td key={week.week} className="px-2">
                    <div className="flex flex-col items-center gap-1">
                      {week.games.length === 0 ? (
                        <Badge variant="fail">blank</Badge>
                      ) : (
                        week.games.map((game, i) => (
                          <Badge key={i} variant={difficultyTone(game.difficulty)}>
                            {game.opponent} {game.home ? "H" : "A"} {game.difficulty}
                          </Badge>
                        ))
                      )}
                    </div>
                  </Td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {outlook.clear > 0 && (
        <CardNote>
          {outlook.runs.length ? `${outlook.clear} others` : `All ${outlook.clear}`}: no blanks, doubles or hard
          runs through GW{last}.
        </CardNote>
      )}
    </>
  );
}
