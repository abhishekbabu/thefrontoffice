import { useEffect, useRef } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { type Competition, type ItemDecision, type ItemMark, type Judgment, type League, type ScoutReport, type Summary } from "@/lib/types";
import { keys, useCapabilities } from "@/lib/queries";
import { moment } from "@/lib/times";
import { offers } from "@/lib/views";
import { ActionList } from "@/components/league/actions";
import { WhyButton, staleVerdicts } from "@/components/league/verdicts";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Busy, QueryState } from "@/components/ui/state";
import { StatGrid, StatList, StatStrip } from "@/components/ui/stat";
import { LineupCard, SideCard, rowsOf } from "@/components/league/lineup";
import { useDrawers } from "@/components/league/drawers";
import { ErrorNote } from "@/components/ui/error-note";
import { LeagueHeader } from "@/components/league/page-header";
import { BestTrade } from "@/components/league/best-trade";
import { Categories } from "@/components/league/categories";
import {
  WeekPane,
  WeekStepper,
  useWeekParam,
} from "@/components/league/week-stepper";

/**
 * Judge again on arrival where the server says the week has moved on from the
 * kept judgment — an item it never saw, or half a day of changes. Once per
 * league for as long as the page is open: a judgment that fails, or comes
 * back still due, is not retried in a loop.
 */
export function useJudgeWhenDue(
  due: boolean,
  scope: string,
  judge: { mutate: () => void; isPending: boolean },
) {
  const asked = useRef(new Set<string>());
  const { mutate, isPending } = judge;

  useEffect(() => {
    if (!due || isPending || asked.current.has(scope)) return;

    asked.current.add(scope);

    mutate();
  }, [due, isPending, scope, mutate]);
}

/**
 * The matchup: where you stand, what you are fielding, and who against — this week, or any other.
 *
 * Complete without a model: everything is read or computed from league state,
 * so the page is whole the moment it opens. Where a model is configured it
 * annotates what is already here — Judge fills each to-do with a verdict and
 * adds the moves the list missed, in place — rather than producing a page of
 * its own to be read beside this one. The last judgment shows on load, from
 * where it was kept, and is asked again only once the week has moved on
 * from it — the server's `due`, never merely a reload.
 *
 * Another week opens from the stepper, the arrow keys or a swipe, and is named
 * in the address (`?week=7`) so it can be linked and Back returns from it. It
 * shows that week's lineups and score and no to-do list, which is only ever
 * about the week being played.
 */
export function MatchupPanel({
  competition,
  league,
}: {
  competition: Competition;
  league: League;
}) {
  const { openPlayer, openComparison, drawer } = useDrawers(competition, league);

  const ai = useCapabilities().data?.ai ?? false;
  const leagueApi = api.league(competition.key, league.league_id);

  const summaryKey = keys.week(competition.key, league.league_id);

  const week = useQuery<Summary, Error>({
    queryKey: summaryKey,
    queryFn: leagueApi.week,
  });

  // The week being played is the summary's; any other is asked for by number.
  const {
    browsing,
    shown: onWeek,
    step,
    swipe,
  } = useWeekParam(
    competition.browses_weeks ? (week.data?.weeks ?? undefined) : undefined,
  );

  const other = useQuery<Summary, Error>({
    queryKey: keys.weekOf(competition.key, league.league_id, browsing),
    queryFn: () => leagueApi.weekOf(browsing!),
    enabled: browsing !== null,
    // The last week stays up while the next loads, rather than the page blanking on every step.
    placeholderData: keepPreviousData,
  });

  const shown = browsing === null ? week : other;

  // The last judgment, read without asking the model anything: judging is a
  // click, and a reload should not throw the answer away.
  const judgmentKey = keys.judgment(competition.key, league.league_id);

  const judgment = useQuery<Judgment | null, Error>({
    queryKey: judgmentKey,
    queryFn: leagueApi.judgment,
    enabled: ai && Boolean(week.data?.actions),
  });

  const queryClient = useQueryClient();

  // The week carries each item's verdict, so a new judgment is read back
  // through it as well as through the judgment's own time and moves.
  const judge = useMutation<ScoutReport, Error>({
    mutationFn: leagueApi.judge,
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: judgmentKey }),
        queryClient.invalidateQueries({ queryKey: summaryKey }),
      ]),
  });

  const report = judgment.data?.answer;

  useJudgeWhenDue(
    ai && judgment.data?.due === true,
    `${competition.key}:${league.league_id}`,
    judge,
  );

  // The decision answers with the item's new mark, which goes straight onto
  // its row: re-reading the week would take a second or two for one field.
  const decide = useMutation<ItemMark, Error, ItemDecision>({
    mutationFn: leagueApi.decide,
    onSuccess: (mark, decision) =>
      queryClient.setQueryData<Summary>(summaryKey, (week) =>
        week?.actions
          ? {
              ...week,
              actions: week.actions.map((action) =>
                action.key === decision.key ? { ...action, mark } : action,
              ),
            }
          : week,
      ),
  });

  return (
    <>
      {/* The week is what this page is about, so it belongs in the header
          rather than a row down among the figures. */}
      <LeagueHeader
        competition={competition}
        league={league}
        meta={[
          shown.data?.weeks ? undated(shown.data.window) : shown.data?.window,
          league.detail,
        ]
          .filter(Boolean)
          .join(" · ")}
      >
        {onWeek && (
          <WeekStepper
            range={onWeek}
            onStep={step}
            word={competition.week_word}
          />
        )}
      </LeagueHeader>
      {/* Only what no card below says: the score once there is one, the chances. */}
      <StatStrip stats={shown.data?.headline ?? []} />

      <QueryState query={shown} lines={4} />

      {shown.data && (
        <WeekPane
          week={shown.data.weeks?.week ?? 0}
          pending={shown.isPlaceholderData}
          // Two across once the page has the room: what to do beside the
          // lineups it acts on, rather than a to-do stretched past reading.
          className="grid touch-pan-y grid-cols-1 items-start gap-4 p-5 @min-[96rem]:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]"
          {...swipe}
        >
          <div className="flex min-w-0 flex-col gap-4 empty:hidden">
            {judge.isError && <ErrorNote error={judge.error} className="m-0" />}
            {decide.isError && (
              <ErrorNote error={decide.error} className="m-0" />
            )}
            {shown.data.actions && (
              <ActionList
                actions={shown.data.actions}
                suggested={report?.moves}
                onOpen={openPlayer}
                onCompare={openComparison}
                onDecide={(decision) => decide.mutate(decision)}
                deciding={decide.isPending}
                detail={(action) =>
                  action.kind === "trade" &&
                  offers(competition, "trades") && (
                    <BestTrade competition={competition} league={league} onCompare={openComparison} />
                  )
                }
                footer={
                  ai
                    ? (action, controls) =>
                        action.key && (
                          <WhyButton action={action} beside={controls} />
                        )
                    : undefined
                }
                aside={
                  // Only where a model is configured: a control that cannot
                  // work would be an offer and then a refusal.
                  ai && (
                    <span className="flex items-center gap-2 normal-case tracking-normal">
                      {judgment.data && !judge.isPending && (
                        <JudgedAt
                          at={judgment.data.answered_at}
                          stale={staleVerdicts(shown.data.actions)}
                        />
                      )}
                      {judge.isPending && <Busy>judging…</Busy>}
                      <IconButton
                        label={
                          judgment.data ? "Judge again" : "Judge this list"
                        }
                        icon={<Sparkles />}
                        onClick={() => judge.mutate()}
                        disabled={judge.isPending}
                      />
                    </span>
                  )
                }
              />
            )}

            {shown.data.categories.length > 0 && (
              <Categories lines={shown.data.categories} />
            )}
          </div>

          <div className="min-w-0 @min-[96rem]:col-start-2 @min-[96rem]:row-span-2 @min-[96rem]:row-start-1">
            <div className="@container flex flex-col gap-4">
              {shown.data.opponent ? (
                <div className="grid grid-cols-1 gap-4 @min-[60rem]:grid-cols-2">
                  {/* Side by side once their column fits two (about 470px each,
                      what an NBA row's per-game line needs), stacked before that:
                      a 1920px screen has the to-do beside them, not room for both across. */}
                  {/* Both sides draw the same columns and row heights, read from either, so slot N sits beside slot N. */}
                  <SideCard
                    side={shown.data.mine}
                    label="You"
                    onOpen={openPlayer}
                    rows={rowsOf(shown.data.mine, shown.data.opponent)}
                  />
                  <SideCard
                    side={shown.data.opponent}
                    label="Opponent"
                    onOpen={openPlayer}
                    rows={rowsOf(shown.data.mine, shown.data.opponent)}
                  />
                </div>
              ) : (
                <LineupCard
                  title="Your lineup"
                  lineup={shown.data.mine?.lineup ?? []}
                  bench={shown.data.mine?.bench ?? []}
                  reserve={shown.data.mine?.reserve ?? []}
                  openSpots={shown.data.mine?.open_spots ?? 0}
                  onOpen={openPlayer}
                />
              )}
            </div>
          </div>

          {/* Back in the first column under the to-do on a wide page; after the
              lineups, as before, on a narrow one. */}
          <div className="flex min-w-0 flex-col gap-4 empty:hidden @min-[96rem]:col-start-1">
            {shown.data.boosts && shown.data.boosts.stats.length > 0 && (
              <Card>
                <CardHeader>
                  <span>{shown.data.boosts.title}</span>
                  {shown.data.boosts.note && (
                    <span>{shown.data.boosts.note}</span>
                  )}
                </CardHeader>
                <StatGrid stats={shown.data.boosts.stats} />
              </Card>
            )}

            {/* Only what a row cannot say for itself: a blank or a double gameweek
              changes what a whole club's players are worth. */}
            {shown.data.fixtures.length > 0 && (
              <Card>
                <CardHeader>
                  <span>Watch out for</span>
                </CardHeader>
                <StatList stats={shown.data.fixtures} className="px-4 py-1" />
              </Card>
            )}

            {!shown.data.opponent && (
              <Badge variant="muted" appearance="label">
                No opponent this {competition.week_word ?? "week"}
              </Badge>
            )}
          </div>
        </WeekPane>
      )}
      {drawer}
    </>
  );
}

/**
 * When the list was last judged, and — once for the whole list rather than on
 * every row — that some of it has changed since. Said in words, with the
 * color only to find it.
 */
export function JudgedAt({ at, stale }: { at: string; stale: boolean }) {
  return (
    <span className="font-normal">
      judged {moment(at)}
      {stale && <span className="text-warn"> · stale</span>}
    </span>
  );
}

/** A window without its leading "Week 11", "GW 11" or "Gameweek 11": the stepper already says which. */
export function undated(window: string): string {
  return window.replace(/^(Week|GW|Gameweek) \d+( · )?/, "");
}
