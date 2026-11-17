import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { m } from "motion/react";
import { api, type ActivityRow, type Competition, type League, type LeagueSchedule, type TeamRef } from "@/lib/api";
import { keys } from "@/lib/queries";
import { StatStrip } from "@/components/ui/stat";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { ListCard } from "@/components/ui/list";
import { ToggleChip } from "@/components/ui/toggle";
import { Table, Td, Th } from "@/components/ui/table";
import { clickable } from "@/lib/clickable";
import { Empty, QueryState } from "@/components/ui/state";
import { RosterTable, useSortedRoster } from "@/components/ui/roster-table";
import { usePlayerDrawer } from "@/components/ui/player";
import { ExternalLink } from "@/components/ui/external-link";
import { rise } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { Tabs } from "@/components/ui/tabs";
import { MoveDrawer, MoveRow, backTo } from "@/components/ui/move";
import { LeagueHeader } from "@/components/ui/page-header";

/**
 * The rest of the league: the table, everybody's rosters, and what they have done.
 *
 * Everyone else, where Schedule and Fixtures are your own season and its real
 * games. Tabs rather than three cards down one page because they are read one
 * at a time — you come here to check the table, or to see what you missed.
 */
type TabId = "standings" | "rosters" | "activity";

const TABS: { id: TabId; label: string }[] = [
  { id: "standings", label: "Table" },
  { id: "rosters", label: "Rosters" },
  { id: "activity", label: "Activity" },
];

export function LeaguePanel({ competition, league }: { competition: Competition; league: League }) {
  const schedule = useQuery<LeagueSchedule, Error>({
    queryKey: keys.schedule(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).schedule,
  });

  // Rosters come from their own call rather than the schedule: browsing them
  // is a different question, and the season view should not wait on it.
  const teams = useQuery<TeamRef[], Error>({
    queryKey: keys.teams(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).teams,
  });

  // Only the sections this platform actually answers. A tab that is always
  // empty is worse than one that is not there: FPL publishes no transfer feed,
  // and a category league has no fixture list.
  const available = TABS.filter((tab) =>
    tab.id === "rosters" ? (teams.data?.length ?? 0) > 0 : (schedule.data?.[tab.id]?.length ?? 0) > 0,
  );
  const [tab, setTab] = useState<TabId>("standings");
  const [team, setTeam] = useState<string | null>(null);
  const current = available.find((t) => t.id === tab)?.id ?? available[0]?.id;

  return (
    <>
      <LeagueHeader league={league}>
        {available.length > 1 && (
          <Tabs tabs={available} current={current} onPick={setTab} />
        )}
      </LeagueHeader>
      {/* The season in figures, here rather than on the week: how it is going, not what Sunday needs. */}
      <StatStrip stats={schedule.data?.headline ?? []} />

      <QueryState query={schedule} lines={6} />

      {schedule.data && !current && (
        <Empty
          title="Nothing about the league"
          detail="This platform publishes no table, rosters or activity through its API."
        />
      )}

      {schedule.data && current && (
        <m.div key={current} variants={rise} initial="hidden" animate="shown" className="p-5">
          {current === "standings" && (
            <Standings rows={schedule.data.standings} onOpen={(id) => { setTeam(id); setTab("rosters"); }} />
          )}
          {current === "rosters" && (
            <Rosters competition={competition} league={league} teams={teams.data ?? []} team={team} onPick={setTeam} />
          )}
          {current === "activity" && <Activity competition={competition} league={league} rows={schedule.data.activity} />}
        </m.div>
      )}
    </>
  );
}

/**
 * Somebody else's squad.
 *
 * The reason to look is to see what they are holding before proposing a trade,
 * or to work out how they are beating you — so it opens on your own team only
 * when nothing else has been picked, and every row opens the player.
 */
function Rosters({
  competition,
  league,
  teams,
  team,
  onPick,
}: {
  competition: Competition;
  league: League;
  teams: TeamRef[];
  team: string | null;
  onPick: (teamId: string) => void;
}) {
  const { openPlayer, drawer } = usePlayerDrawer(competition, league);
  const selected = teams.find((t) => t.team_id === team) ?? teams[0];

  const { roster, sort, onSort } = useSortedRoster(
    keys.teamRoster(competition.key, league.league_id, selected?.team_id),
    (order) => api.league(competition.key, league.league_id).teamRoster(selected!.team_id, order),
    Boolean(selected),
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-1.5">
        {teams.map((t) => (
          <ToggleChip key={t.team_id} pressed={t.team_id === selected?.team_id} onClick={() => onPick(t.team_id)}>
            <span className="max-w-[14rem] truncate">{t.name}</span>
            {t.is_mine && (
              <span className="font-mono text-[10px] uppercase tracking-[0.08em] opacity-70">you</span>
            )}
          </ToggleChip>
        ))}
      </div>

      {selected && (
        <Card>
          <CardHeader>
            <span className="flex items-center gap-1">
              {selected.name}
              <ExternalLink href={selected.url} label={`Open ${selected.name} on the platform`} />
            </span>
            <span>{selected.detail}</span>
          </CardHeader>
          <QueryState query={roster} lines={5} />
          {roster.data && (
            <RosterTable
              players={roster.data}
              empty={{ title: "Nothing on this roster" }}
              onOpen={openPlayer}
              sort={sort}
              onSort={onSort}
            />
          )}
        </Card>
      )}
      {drawer}
    </div>
  );
}

function Standings({
  rows,
  onOpen,
}: {
  rows: LeagueSchedule["standings"];
  onOpen: (teamId: string) => void;
}) {
  // Only the columns this league fills: FPL has no waiver budget, and a league
  // that is not simulated has no playoff chance.
  const has = (key: "record" | "points_against" | "waiver_budget" | "waiver_order" | "playoffs") =>
    rows.some((row) => row[key]);
  return (
    <Card>
      <CardHeader>
        <span>Table</span>
        <span>{rows.length} teams</span>
      </CardHeader>
      <Table>
        <thead>
          <tr>
            <Th className="w-8 text-right">#</Th>
            <Th>Team</Th>
            {has("record") && <Th className="text-right">Record</Th>}
            <Th className="text-right">{has("points_against") ? "PF" : "Pts"}</Th>
            {has("points_against") && <Th className="text-right">PA</Th>}
            {has("waiver_budget") && <Th className="text-right">FAAB</Th>}
            {has("waiver_order") && <Th className="text-right">Waiver</Th>}
            {has("playoffs") && <Th className="text-right">Playoffs</Th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={`${row.rank}-${row.name}`}
              {...clickable(row.team_id ? () => onOpen(row.team_id) : undefined)}
              className={cn(row.team_id && "cursor-pointer hover:bg-muted", row.is_mine && "bg-muted/60")}
            >
              <Td className="text-right font-mono text-muted-foreground">{row.rank}</Td>
              <Td>
                <span className="flex min-w-0 items-center gap-2">
                  <span className={cn("truncate", row.is_mine && "font-semibold")}>{row.name}</span>
                  {row.is_mine && (
                    <Badge variant="muted" appearance="label" className="shrink-0">
                      you
                    </Badge>
                  )}
                  {row.detail && (
                    <span className="hidden truncate font-mono text-[11px] text-muted-foreground sm:block">
                      {row.detail}
                    </span>
                  )}
                </span>
              </Td>
              {has("record") && <Td className="text-right font-mono">{row.record}</Td>}
              <Td className="text-right font-mono">{row.points}</Td>
              {has("points_against") && <Td className="text-right font-mono">{row.points_against}</Td>}
              {has("waiver_budget") && <Td className="text-right font-mono">{row.waiver_budget}</Td>}
              {has("waiver_order") && <Td className="text-right font-mono">{row.waiver_order}</Td>}
              {has("playoffs") && <Td className="text-right font-mono text-muted-foreground">{row.playoffs}</Td>}
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

/**
 * What the league did lately, newest first; a row opens the move in full.
 *
 * The row says it in one line — "+A, -B" — which is all a scan needs. The
 * move itself names each player and whose roster took or lost him, which a
 * trade needs, and any bid behind a claim. A player there opens his page.
 */
function Activity({ competition, league, rows }: { competition: Competition; league: League; rows: ActivityRow[] }) {
  const [open, setOpen] = useState<ActivityRow | null>(null);
  const { openPlayer, drawer } = usePlayerDrawer(competition, league);
  return (
    <>
      <ListCard title="Recent activity" count={`${rows.length} moves`}>
        {rows.map((row, i) => (
          <MoveRow key={`${row.when}-${i}`} move={row} onOpen={setOpen} />
        ))}
      </ListCard>
      <MoveDrawer
        move={open}
        competition={competition.key}
        league={league.league_id}
        onClose={() => setOpen(null)}
        onOpenPlayer={(id) => {
          const from = open!;
          setOpen(null);
          openPlayer(id, backTo(from, () => setOpen(from)));
        }}
      />
      {drawer}
    </>
  );
}
