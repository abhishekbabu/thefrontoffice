import { Fragment, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, type Competition, type League, type LeagueSchedule, type Match, type Slate, type Summary } from "@/lib/api";
import { keys } from "@/lib/queries";
import { kickoff } from "@/lib/format";
import { toneText } from "@/lib/tone";
import { cn } from "@/lib/utils";
import { ListCard, ListHeading, ListRow } from "@/components/ui/list";
import { Label, Meta } from "@/components/ui/label";
import { Empty, QueryState } from "@/components/ui/state";
import { LeagueHeader } from "@/components/league/page-header";
import { WeekPane, WeekStepper, useWeekParam } from "@/components/league/week-stepper";
import { SlideOver, SlideOverHeader } from "@/components/ui/dialog";
import { useDrawers } from "@/components/league/drawers";

/**
 * The real games a fantasy week is made of, by kickoff, with whose players are in each and who has a bye.
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
  const { openPlayer, drawer } = useDrawers(competition, league);

  const summary = useQuery<Summary, Error>({
    queryKey: keys.summary(competition.key, league.league_id),
    queryFn: leagueApi.summary,
    enabled: browses,
  });
  const { shown, step, swipe } = useWeekParam(browses ? (summary.data?.weeks ?? undefined) : undefined);

  const games = useQuery<Slate, Error>({
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

  const rows = browses ? games.data?.games : schedule.data?.matches;
  const byes = (browses && games.data?.byes) || [];
  const note = (browses && games.data?.note) || "";
  return (
    <>
      <LeagueHeader league={league}>
        {shown && <WeekStepper range={shown} onStep={step} word={competition.week_word} />}
      </LeagueHeader>
      <QueryState query={browses ? (shown ? games : summary) : schedule} lines={6} />
      {rows && rows.length === 0 && <Empty title={`No games this ${competition.week_word ?? "week"}`} />}
      {rows && rows.length > 0 && (
        <WeekPane
          week={shown?.week ?? 0}
          pending={browses && games.isPlaceholderData}
          className="touch-pan-y p-5"
          {...swipe}
        >
          <Games rows={rows} byes={byes} note={note} onOpen={setOpen} />
        </WeekPane>
      )}
      <SlideOver
        open={open !== null}
        onClose={() => setOpen(null)}
        label={open ? `${open.away} at ${open.home}` : "Game"}
        className="max-w-lg border-l border-border"
      >
        {open && (
          <GameDetail
            game={open}
            onClose={() => setOpen(null)}
            onOpen={(id) => {
              const from = open;
              setOpen(null);
              openPlayer(id, { label: `${from.away} at ${from.home}`, onBack: () => setOpen(from) });
            }}
          />
        )}
      </SlideOver>
      {drawer}
    </>
  );
}

/** Who you and your opponent have in one game; a player opens in its place, with the way back to it. */
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
                  <Meta className="shrink-0">{p.detail}</Meta>
                </ListRow>
              ))}
            </ListCard>
          ))}
      </div>
    </>
  );
}

/** When a game starts: its kickoff in the viewer's zone where known, the day the schedule gives otherwise. */
const slot = (game: Match) => (game.kickoff ? kickoff(game.kickoff) : game.label);

/**
 * The week's games under one heading per kickoff, so a time is said once
 * rather than on every row of a Sunday. Rows arrive in kickoff order, so a
 * slot is a run of them.
 */
export function Games({
  rows,
  byes = [],
  note = "",
  onOpen,
}: {
  rows: Match[];
  /** Clubs with no game this week. */
  byes?: string[];
  /** Why the list is not to be read as complete — a schedule not final yet; empty for most weeks. */
  note?: string;
  onOpen?: (game: Match) => void;
}) {
  return (
    <ListCard title="Fixtures" count={`${rows.length} games`}>
      {note && (
        <ListRow>
          <span className={cn("min-w-0 flex-1 text-[12.5px]", toneText("warning"))}>{note}</span>
        </ListRow>
      )}
      {byes.length > 0 && (
        <ListRow>
          <Label className="shrink-0">Byes</Label>
          <span className="min-w-0 flex-1 font-mono text-[12px]">{byes.join(", ")}</span>
        </ListRow>
      )}
      {rows.map((row, i) => {
        const before = rows[i - 1];
        return (
          <Fragment key={`${row.home}-${row.away}-${i}`}>
            {(!before || slot(before) !== slot(row)) && <ListHeading>{slot(row)}</ListHeading>}
            <ListRow
              className="flex-col items-stretch gap-1"
              // A game opens where somebody's players are in it: the rest have nothing to show.
              onClick={onOpen && (row.yours.length || row.theirs.length) ? () => onOpen(row) : undefined}
            >
              <div className="flex items-baseline gap-3">
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
              </div>
              <Holders game={row} />
            </ListRow>
          </Fragment>
        );
      })}
    </ListCard>
  );
}

/** Whose players are in a game, by name: yours, then your opponent's, each side labelled in words. */
function Holders({ game }: { game: Match }) {
  const sides = [
    { label: "You", players: game.yours, tone: "" },
    { label: "Opp", players: game.theirs, tone: "text-muted-foreground" },
  ].filter((side) => side.players.length > 0);
  if (sides.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[12px]">
      {sides.map((side) => (
        <span key={side.label} className="min-w-0">
          <Label className="mr-1.5">{side.label}</Label>
          <span className={side.tone}>{side.players.map((p) => p.name).join(", ")}</span>
        </span>
      ))}
    </div>
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
