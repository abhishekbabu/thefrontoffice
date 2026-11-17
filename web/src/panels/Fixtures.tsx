import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, type Competition, type League, type LeagueSchedule, type Match, type Summary } from "@/lib/api";
import { keys } from "@/lib/queries";
import { kickoff } from "@/lib/format";
import { toneText } from "@/lib/tone";
import { cn } from "@/lib/utils";
import { ListCard, ListRow } from "@/components/ui/list";
import { Empty, QueryState } from "@/components/ui/state";
import { LeagueHeader } from "@/components/ui/page-header";
import { WeekStepper, useWeekParam } from "@/components/ui/week-stepper";
import { SlideOver, SlideOverHeader } from "@/components/ui/dialog";
import { usePlayerDrawer } from "@/components/ui/player";

/**
 * The real games a fantasy week is made of, with the ones you have players in marked.
 *
 * Where the competition pages through the season, so does this: the same
 * stepper, keys and swipe as the Matchup page, against the same range, read
 * from the same summary. Elsewhere it is the week being played, from the
 * league's schedule.
 */
export function FixturesPanel({ competition, league }: { competition: Competition; league: League }) {
  const leagueApi = api.league(competition.key, league.league_id);
  const browses = competition.browses_weeks;
  const [open, setOpen] = useState<Match | null>(null);
  const { openPlayer, drawer } = usePlayerDrawer(competition, league);

  const summary = useQuery<Summary, Error>({
    queryKey: keys.summary(competition.key, league.league_id),
    queryFn: leagueApi.summary,
    enabled: browses,
  });
  const { shown, step, swipe } = useWeekParam(browses ? (summary.data?.weeks ?? undefined) : undefined);

  const games = useQuery<Match[], Error>({
    queryKey: keys.games(competition.key, league.league_id, shown?.week ?? null),
    queryFn: () => leagueApi.gamesOf(shown!.week),
    enabled: browses && shown !== undefined,
    placeholderData: keepPreviousData,
  });
  const schedule = useQuery<LeagueSchedule, Error>({
    queryKey: keys.schedule(competition.key, league.league_id),
    queryFn: leagueApi.schedule,
    enabled: !browses,
  });

  const rows = browses ? games.data : schedule.data?.matches;
  return (
    <>
      <LeagueHeader league={league}>
        {shown && <WeekStepper range={shown} onStep={step} />}
      </LeagueHeader>
      <QueryState query={browses ? (shown ? games : summary) : schedule} lines={6} />
      {rows && rows.length === 0 && <Empty title="No games this week" />}
      {rows && rows.length > 0 && (
        <div className="touch-pan-y p-5" {...swipe}>
          <Games rows={rows} onOpen={setOpen} />
        </div>
      )}
      <SlideOver
        open={open !== null}
        onClose={() => setOpen(null)}
        label={open ? `${open.away} at ${open.home}` : "Game"}
        className="max-w-lg border-l border-border"
      >
        {open && <GameDetail game={open} onClose={() => setOpen(null)} onOpen={openPlayer} />}
      </SlideOver>
      {drawer}
    </>
  );
}

/** Who you and your opponent have in one game; a player opens over it, and closing him returns here. */
function GameDetail({ game, onClose, onOpen }: { game: Match; onClose: () => void; onOpen: (id: string) => void }) {
  return (
    <>
      <SlideOverHeader
        title={`${game.away} at ${game.home}`}
        meta={[game.kickoff ? kickoff(game.kickoff) : game.label, game.detail].filter(Boolean).join(" · ")}
        onClose={onClose}
      />
      <div className="flex flex-col gap-4 p-5">
        {[
          { title: "Yours", players: game.yours },
          { title: "Your opponent's", players: game.theirs },
        ]
          .filter((side) => side.players.length > 0)
          .map((side) => (
            <ListCard key={side.title} title={side.title} count={`${side.players.length}`}>
              {side.players.map((p) => (
                <ListRow key={p.player_id} onClick={() => onOpen(p.player_id)}>
                  <span className="min-w-0 flex-1 truncate">{p.name}</span>
                  <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{p.detail}</span>
                </ListRow>
              ))}
            </ListCard>
          ))}
      </div>
    </>
  );
}

export function Games({ rows, onOpen }: { rows: Match[]; onOpen?: (game: Match) => void }) {
  return (
    <ListCard title="Fixtures" count={`${rows.length} games`}>
      {rows.map((row, i) => (
        <ListRow
          key={`${row.home}-${row.away}-${i}`}
          // A game opens where somebody's players are in it: the rest have nothing to show.
          onClick={onOpen && (row.yours.length || row.theirs.length) ? () => onOpen(row) : undefined}
        >
          <span className="w-36 shrink-0 font-mono text-[11px] text-muted-foreground">
            {row.kickoff ? kickoff(row.kickoff) : row.label}
          </span>
          <span className="min-w-0 flex-1 font-mono text-[12.5px]">
            <Side club={row.away} score={row.away_score} other={row.home_score} />{" "}
            <span className="text-muted-foreground">at</span>{" "}
            <Side club={row.home} score={row.home_score} other={row.away_score} />
          </span>
          {row.detail && (
            <span className={cn("shrink-0 font-mono text-[11px]", toneText(row.tone, "text-muted-foreground"))}>
              {row.detail}
            </span>
          )}
        </ListRow>
      ))}
    </ListCard>
  );
}

/** A club, and its score once the game has kicked off; the side ahead in weight, which reads without color. */
function Side({ club, score, other }: { club: string; score?: number | null; other?: number | null }) {
  if (score == null) return <>{club}</>;
  const ahead = other != null && score > other;
  return (
    <span className={cn(ahead && "font-semibold")}>
      {club} <span className="tabular-nums">{score}</span>
    </span>
  );
}
