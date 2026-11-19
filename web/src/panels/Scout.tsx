import { useEffect, useRef } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import {
  api,
  type CategoryLine,
  type Competition,
  type ItemDecision,
  type ItemMark,
  type Judgment,
  type League,
  type ScoutReport,
  type Summary,
  type TradeIdea,
  type Trades,
} from "@/lib/api";
import { Link } from "react-router-dom";
import { keys, useCapabilities } from "@/lib/queries";
import { moment, percent, percentPoints, signed } from "@/lib/format";
import { href, offers } from "@/lib/route";
import { ActionList, WhyButton, staleVerdicts } from "@/components/ui/actions";
import { IconButton } from "@/components/ui/icon-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Busy, QueryState } from "@/components/ui/state";
import { StatGrid, StatList, StatStrip } from "@/components/ui/stat";
import { LineupCard, SideCard, Swaps, underWay } from "@/components/ui/lineup";
import { usePlayerDrawer } from "@/components/ui/player";
import { ErrorNote } from "@/components/ui/error-note";
import { LeagueHeader } from "@/components/ui/page-header";
import { WeekPane, WeekStepper, useWeekParam } from "@/components/ui/week-stepper";
import { Label } from "@/components/ui/label";
import { Table, Td, Th } from "@/components/ui/table";
import { cn } from "@/lib/utils";

/**
 * Judge again on arrival where the server says the week has moved on from the
 * kept judgment — an item it never saw, or half a day of changes. Once per
 * league for as long as the page is open: a judgment that fails, or comes
 * back still due, is not retried in a loop.
 */
export function useJudgeWhenDue(due: boolean, scope: string, judge: { mutate: () => void; isPending: boolean }) {
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
export function ScoutPanel({ competition, league }: { competition: Competition; league: League }) {
  const { openPlayer, drawer } = usePlayerDrawer(competition, league);

  const ai = useCapabilities().data?.ai ?? false;
  const leagueApi = api.league(competition.key, league.league_id);

  const summaryKey = keys.summary(competition.key, league.league_id);
  const week = useQuery<Summary, Error>({ queryKey: summaryKey, queryFn: leagueApi.summary });

  // The week being played is the summary's; any other is asked for by number.
  const { browsing, shown: onWeek, step, swipe } = useWeekParam(
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
    mutationFn: leagueApi.scout,
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: judgmentKey }),
        queryClient.invalidateQueries({ queryKey: summaryKey }),
      ]),
  });
  const report = judgment.data?.answer;
  useJudgeWhenDue(ai && judgment.data?.due === true, `${competition.key}:${league.league_id}`, judge);
  // The decision answers with the item's new mark, which goes straight onto
  // its row: re-reading the week would take a second or two for one field.
  const decide = useMutation<ItemMark, Error, ItemDecision>({
    mutationFn: leagueApi.decide,
    onSuccess: (mark, decision) =>
      queryClient.setQueryData<Summary>(summaryKey, (week) =>
        week?.actions
          ? {
              ...week,
              actions: week.actions.map((action) => (action.key === decision.key ? { ...action, mark } : action)),
            }
          : week,
      ),
  });

  return (
    <>
      {/* The week is what this page is about, so it belongs in the header
          rather than a row down among the figures. */}
      <LeagueHeader
        league={league}
        meta={[shown.data?.weeks ? undated(shown.data.window) : shown.data?.window, league.detail]
          .filter(Boolean)
          .join(" · ")}
      >
        {onWeek && <WeekStepper range={onWeek} onStep={step} />}
      </LeagueHeader>
      {/* Only what no card below says: the score once there is one, the chances. */}
      <StatStrip stats={shown.data?.headline ?? []} />

      <QueryState query={shown} lines={4} />

      {shown.data && (
        <WeekPane
          week={shown.data.weeks?.week ?? 0}
          pending={shown.isPlaceholderData}
          className="flex touch-pan-y flex-col gap-4 p-5"
          {...swipe}
        >
          {judge.isError && <ErrorNote error={judge.error} className="m-0" />}
          {decide.isError && <ErrorNote error={decide.error} className="m-0" />}
          {shown.data.actions && (
            <ActionList
              actions={shown.data.actions}
              suggested={report?.moves}
              onOpen={openPlayer}
              onDecide={(decision) => decide.mutate(decision)}
              deciding={decide.isPending}
              detail={(action) =>
                action.kind === "trade" &&
                offers(competition, "trades") && <BestTrade competition={competition} league={league} />
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
                      <JudgedAt at={judgment.data.answered_at} stale={staleVerdicts(shown.data.actions)} />
                    )}
                    {judge.isPending && <Busy>judging…</Busy>}
                    <IconButton
                      label={judgment.data ? "Judge again" : "Judge this list"}
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

          {shown.data.opponent ? (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              {/* Both sides draw a points column from the week's first kickoff on either, so they stay aligned. */}
              <SideCard
                side={shown.data.mine}
                label="You"
                onOpen={openPlayer}
                started={underWay(shown.data.mine, shown.data.opponent)}
              />
              <SideCard
                side={shown.data.opponent}
                label="Opponent"
                onOpen={openPlayer}
                started={underWay(shown.data.mine, shown.data.opponent)}
              />
            </div>
          ) : (
            <LineupCard
              title="Your lineup"
              lineup={shown.data.mine?.lineup ?? []}
              bench={shown.data.mine?.bench ?? []}
              reserve={shown.data.mine?.reserve ?? []}
              openSpots={shown.data.mine?.open_spots ?? 0}
              swaps={shown.data.swaps}
              onOpen={openPlayer}
            />
          )}

          {/* Shown beside the lineups when there is an opponent, since the
              swaps then have no card of their own to live in. A competition
              with a to-do list sends none: they are items on it. */}
          {shown.data.opponent && shown.data.swaps.length > 0 && (
            <Card>
              <Swaps swaps={shown.data.swaps} />
            </Card>
          )}

          {shown.data.boosts && shown.data.boosts.stats.length > 0 && (
            <Card>
              <CardHeader>
                <span>{shown.data.boosts.title}</span>
                {shown.data.boosts.note && <span>{shown.data.boosts.note}</span>}
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
              No opponent this week
            </Badge>
          )}
        </WeekPane>
      )}
      {drawer}
    </>
  );
}

/**
 * The best trade the Trades page has, under the deadline item: an item that
 * says only "trade" leaves you to go and find out what. Read from the same
 * query as that page, so it is computed once for both, and linked to it for
 * the rest. The gain shown is the figure that page orders by, so "best"
 * means the same thing in both places. Its absence is said, tersely: no
 * offer is an answer.
 */
export function BestTrade({ competition, league }: { competition: Competition; league: League }) {
  const trades = useQuery<Trades, Error>({
    queryKey: keys.trades(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).trades,
  });
  const best = trades.data?.ideas[0];
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]">
      {trades.isLoading && <Busy>finding trades…</Busy>}
      {best && trades.data && (
        <>
          <span>
            Best: give {best.giving.join(" and ")} for {best.receiving.join(", ")} with {best.team}
          </span>
          <Badge variant="ok" appearance="pill" className="tabular-nums">
            {gain(best, trades.data.ranked_by)}
          </Badge>
        </>
      )}
      {trades.data && !best && <span className="text-muted-foreground">No trades worth offering.</span>}
      <Link
        to={href(competition.key, league.league_id, "trades")}
        className="font-mono text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground"
      >
        All trades
      </Link>
    </div>
  );
}

/** What a trade gains you on the figure the list is ranked by, in words: '+21.4 pts rest of season', 'playoff odds +4.0 pts'. */
export function gain(idea: TradeIdea, ranked: Trades["ranked_by"]): string {
  if (ranked === "playoffs_change") return `playoff odds ${percentPoints(idea.playoffs_change)}`;
  return `${signed(idea.total)} pts rest of season`;
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

const LEAD: Record<NonNullable<CategoryLine["lead"]>, { word: string; tone: string }> = {
  mine: { word: "You", tone: "text-ok" },
  theirs: { word: "Them", tone: "text-warn" },
  even: { word: "Level", tone: "text-muted-foreground" },
};

/** A chance of winning a category, toned as the header's win chance is; the figure itself carries it. */
function chanceTone(win: number): string {
  return win >= 0.6 ? "text-ok" : win <= 0.4 ? "text-warn" : "text-muted-foreground";
}

/**
 * A category week, read across: each category, both figures, who leads it,
 * and — where the week is forecast — your chance of winning it.
 *
 * The leader is said in words as well as weight and color, since a category
 * week is won by the count of those words.
 */
export function Categories({ lines }: { lines: CategoryLine[] }) {
  const forecast = lines.some((line) => line.win != null);
  return (
    <Card>
      <CardHeader>
        <span>Categories</span>
        <span>{lines.length} scored</span>
      </CardHeader>
      <Table>
        <thead>
          <tr>
            <Th className="w-16">Cat</Th>
            <Th className="w-20 text-right">You</Th>
            {/* Not the opponent's name, which truncates: the lineup cards below name both teams. */}
            <Th className="w-20 text-right">Them</Th>
            <Th className="text-right">Leads</Th>
            {forecast && <Th className="w-12 text-right">Win</Th>}
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            const lead = line.lead ? LEAD[line.lead] : null;
            return (
              <tr key={line.name} className="font-mono text-[12.5px] [&:last-child>td]:border-b-0">
                <Td>
                  <Label>{line.name}</Label>
                </Td>
                <Td className={cn("text-right", line.lead === "mine" && "font-semibold")}>{line.mine || "—"}</Td>
                <Td className={cn("text-right", line.lead === "theirs" && "font-semibold")}>{line.theirs || "—"}</Td>
                <Td className={cn("text-right text-[11px]", lead?.tone ?? "text-muted-foreground")}>
                  {lead?.word ?? "—"}
                </Td>
                {forecast && (
                  <Td className={cn("text-right", line.win != null ? chanceTone(line.win) : "text-muted-foreground")}>
                    {line.win != null ? percent(line.win) : "—"}
                  </Td>
                )}
              </tr>
            );
          })}
        </tbody>
      </Table>
    </Card>
  );
}

/** A window without its leading "Week 11", "GW 11" or "Gameweek 11": the stepper already says which. */
export function undated(window: string): string {
  return window.replace(/^(Week|GW|Gameweek) \d+( · )?/, "");
}
