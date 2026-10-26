import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { m } from "motion/react";
import {
  api,
  type League,
  type LeagueSchedule,
  type PlayerCard,
  type Competition,
  type TeamRef,
} from "@/lib/api";
import { StatStrip } from "@/components/ui/stat";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { ListCard, ListRow } from "@/components/ui/list";
import { ToggleChip } from "@/components/ui/toggle";
import { Empty, Loading } from "@/components/ui/state";
import { RosterTable } from "@/components/ui/roster-table";
import { usePlayerDrawer } from "@/components/ui/player";
import { ExternalLink } from "@/components/ui/external-link";
import { rise } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { ErrorNote } from "@/components/ui/error-note";
import { LeagueHeader } from "@/components/ui/page-header";

/**
 * The league beyond this week.
 *
 * Four questions that are all "how is the season going" rather than "what do I
 * do about Sunday", which is what the week view is for. They are tabs rather
 * than four cards down one page because they are read one at a time — you come
 * here to check the table, or to see what you missed, not both.
 */
type TabId = "season" | "standings" | "rosters" | "matches" | "activity";

const TABS: { id: TabId; label: string }[] = [
  { id: "season", label: "Season" },
  { id: "standings", label: "Table" },
  { id: "rosters", label: "Rosters" },
  { id: "matches", label: "Fixtures" },
  { id: "activity", label: "Activity" },
];

export function LeaguePanel({ competition, league }: { competition: Competition; league: League }) {
  const schedule = useQuery<LeagueSchedule, Error>({
    queryKey: ["schedule", competition.key, league.league_id],
    queryFn: () => api.schedule(competition.key, league.league_id),
  });

  // Rosters come from their own call rather than the schedule: browsing them
  // is a different question, and the season view should not wait on it.
  const teams = useQuery<TeamRef[], Error>({
    queryKey: ["teams", competition.key, league.league_id],
    queryFn: () => api.teams(competition.key, league.league_id),
  });

  // Only the sections this platform actually answers. A tab that is always
  // empty is worse than one that is not there: FPL publishes no transfer feed,
  // and a category league has no fixture list.
  const available = TABS.filter((tab) =>
    tab.id === "rosters" ? (teams.data?.length ?? 0) > 0 : (schedule.data?.[tab.id]?.length ?? 0) > 0,
  );
  const [tab, setTab] = useState<TabId>("season");
  const [team, setTeam] = useState<string | null>(null);
  const current = available.find((t) => t.id === tab)?.id ?? available[0]?.id;

  return (
    <>
      <LeagueHeader league={league}>
        {available.length > 1 && (
          <div className="flex items-center gap-1" role="tablist">
            {available.map((t) => (
              <button
                key={t.id}
                role="tab"
                aria-selected={t.id === current}
                onClick={() => setTab(t.id)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors",
                  t.id === current ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-muted",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
      </LeagueHeader>
      {/* The season in figures, here rather than on the week: how it is going, not what Sunday needs. */}
      <StatStrip stats={schedule.data?.headline ?? []} />

      {schedule.isLoading && <Loading lines={6} />}
      {schedule.isError && <ErrorNote error={schedule.error} />}

      {schedule.data && !current && (
        <Empty
          title="Nothing beyond this week"
          detail="This platform publishes no season, table or fixture list through its API."
        />
      )}

      {schedule.data && current && (
        <m.div key={current} variants={rise} initial="hidden" animate="shown" className="p-5">
          {current === "season" && <Season rows={schedule.data.season} />}
          {current === "standings" && (
            <Standings rows={schedule.data.standings} onOpen={(id) => { setTeam(id); setTab("rosters"); }} />
          )}
          {current === "rosters" && (
            <Rosters competition={competition} league={league} teams={teams.data ?? []} team={team} onPick={setTeam} />
          )}
          {current === "matches" && <Matches rows={schedule.data.matches} />}
          {current === "activity" && <Activity rows={schedule.data.activity} />}
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

  const roster = useQuery<PlayerCard[], Error>({
    queryKey: ["team-roster", competition.key, league.league_id, selected?.team_id],
    queryFn: () => api.teamRoster(competition.key, league.league_id, selected!.team_id),
    enabled: Boolean(selected),
  });

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
          {roster.isLoading && <Loading lines={5} />}
          {roster.isError && <ErrorNote error={roster.error} />}
          {roster.data && (
            <RosterTable
              players={roster.data}
              empty={{ title: "Nothing on this roster" }}
              onOpen={openPlayer}
            />
          )}
        </Card>
      )}
      {drawer}
    </div>
  );
}

function Season({ rows }: { rows: LeagueSchedule["season"] }) {
  return (
    <ListCard title="Your season" count={`${rows.length} weeks`}>
      {rows.map((row, i) => (
        <Fragment key={row.label}>
          {/* The bracket is a different competition from the weeks before it, so it reads as one. */}
          {row.playoffs && !rows[i - 1]?.playoffs && (
            <div className="border-t border-border bg-muted px-4 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              Playoffs
            </div>
          )}
        <ListRow current={row.is_current}>
          <span className="w-24 shrink-0 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
            {row.label}
          </span>
          <span className="w-32 shrink-0 font-mono text-[11px] text-muted-foreground">{row.date}</span>
          <span className="min-w-0 flex-1 truncate">
            {row.opponent || <span className="text-muted-foreground">{row.detail || "—"}</span>}
          </span>
          {/* Said, not only shaded — the tint is reinforcement. */}
          {row.is_current && (
            <Badge variant="muted" appearance="label" className="shrink-0">
              this week
            </Badge>
          )}
          {row.opponent && row.detail && (
            <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{row.detail}</span>
          )}
          {/* Won and lost are carried by the word as well as the color: state
              in color alone is state a colorblind reader cannot see. */}
          {row.result && (
            <Badge
              variant={row.tone === "good" ? "ok" : row.tone === "warning" ? "fail" : "muted"}
              appearance="pill"
              className="tabular-nums"
            >
              {row.tone === "good" ? "W" : row.tone === "warning" ? "L" : "D"} {row.result}
            </Badge>
          )}
        </ListRow>
        </Fragment>
      ))}
    </ListCard>
  );
}

function Standings({
  rows,
  onOpen,
}: {
  rows: LeagueSchedule["standings"];
  onOpen: (teamId: string) => void;
}) {
  return (
    <ListCard title="Table" count={`${rows.length} teams`}>
      {rows.map((row) => (
        <ListRow
          key={`${row.rank}-${row.name}`}
          current={row.is_mine}
          // A table is a list of teams, so a row is the obvious way in to one.
          onClick={row.team_id ? () => onOpen(row.team_id) : undefined}
        >
          <span className="w-6 shrink-0 text-right font-mono text-[12px] tabular-nums text-muted-foreground">
            {row.rank}
          </span>
          <span className={cn("min-w-0 flex-1 truncate", row.is_mine && "font-semibold")}>{row.name}</span>
          {row.is_mine && (
            <Badge variant="muted" appearance="label" className="shrink-0">
              you
            </Badge>
          )}
          {row.detail && (
            <span className="hidden shrink-0 truncate font-mono text-[11px] text-muted-foreground sm:block">
              {row.detail}
            </span>
          )}
          {row.record && <span className="shrink-0 font-mono text-[11.5px] tabular-nums">{row.record}</span>}
          <span className="w-28 shrink-0 text-right font-mono text-[12px] tabular-nums">{row.points}</span>
          {/* Labelled in the cell rather than by a header the table does not
              have; on a phone the word is left to screen readers. */}
          {row.playoffs && (
            <span className="shrink-0 text-right font-mono text-[11.5px] tabular-nums text-muted-foreground sm:w-28">
              {row.playoffs}
              <span className="sr-only sm:not-sr-only"> playoffs</span>
            </span>
          )}
        </ListRow>
      ))}
    </ListCard>
  );
}

function Matches({ rows }: { rows: LeagueSchedule["matches"] }) {
  return (
    <ListCard title="This week's fixtures" count={`${rows.length} matches`}>
      {rows.map((row, i) => (
        <ListRow key={`${row.home}-${row.away}-${i}`}>
          <span className="w-36 shrink-0 font-mono text-[11px] text-muted-foreground">{row.label}</span>
          <span className="min-w-0 flex-1 font-mono text-[12.5px]">
            {row.away} <span className="text-muted-foreground">at</span> {row.home}
          </span>
          {row.detail && (
            <span className={cn("shrink-0 font-mono text-[11px]", row.tone === "warning" ? "text-warn" : "text-muted-foreground")}>
              {row.detail}
            </span>
          )}
        </ListRow>
      ))}
    </ListCard>
  );
}

function Activity({ rows }: { rows: LeagueSchedule["activity"] }) {
  return (
    <ListCard title="Recent activity" count={`${rows.length} moves`}>
      {rows.map((row, i) => (
        <ListRow key={`${row.when}-${i}`} current={row.tone === "good"}>
          <span className="w-16 shrink-0 font-mono text-[11px] text-muted-foreground">{row.when}</span>
          <span className="w-32 shrink-0 truncate">{row.who}</span>
          <Badge variant="muted" appearance="label" className="shrink-0">
            {row.what}
          </Badge>
          <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-muted-foreground">{row.detail}</span>
        </ListRow>
      ))}
    </ListCard>
  );
}
