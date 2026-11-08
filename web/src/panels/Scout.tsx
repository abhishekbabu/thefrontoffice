import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import {
  api,
  type Competition,
  type ItemDecision,
  type ItemMark,
  type League,
  type RememberedReport,
  type ScoutReport,
  type Summary,
} from "@/lib/api";
import { keys, useCapabilities } from "@/lib/queries";
import { moment } from "@/lib/format";
import { ActionList, WhyThread } from "@/components/ui/actions";
import { IconButton } from "@/components/ui/icon-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Busy, QueryState } from "@/components/ui/state";
import { StatGrid, StatList, StatStrip } from "@/components/ui/stat";
import { LineupCard, SideCard, Swaps } from "@/components/ui/lineup";
import { usePlayerDrawer } from "@/components/ui/player";
import { ErrorNote } from "@/components/ui/error-note";
import { LeagueHeader } from "@/components/ui/page-header";

/**
 * The week: where you stand, what you are fielding, and who against.
 *
 * Complete without a model: everything is read or computed from league state,
 * so the page is whole the moment it opens. Where a model is configured it
 * annotates what is already here — Judge fills each to-do with a verdict and
 * adds the moves the list missed, in place — rather than producing a page of
 * its own to be read beside this one. It never runs on load; the last
 * judgment does, from where it was kept.
 */
export function ScoutPanel({ competition, league }: { competition: Competition; league: League }) {
  const { openPlayer, drawer } = usePlayerDrawer(competition, league);

  const ai = useCapabilities().data?.ai ?? false;
  const leagueApi = api.league(competition.key, league.league_id);

  const summaryKey = keys.summary(competition.key, league.league_id);
  const week = useQuery<Summary, Error>({ queryKey: summaryKey, queryFn: leagueApi.summary });

  // The last judgment, read without asking the model anything: judging is a
  // click, and a reload should not throw the answer away.
  const judgmentKey = keys.judgment(competition.key, league.league_id);
  const judgment = useQuery<RememberedReport | null, Error>({
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
      <LeagueHeader league={league} meta={[week.data?.window, league.detail].filter(Boolean).join(" · ")} />
      <StatStrip stats={week.data?.headline ?? []} />

      <QueryState query={week} lines={4} />

      {week.data && (
        <div className="flex flex-col gap-4 p-5">
          {judge.isError && <ErrorNote error={judge.error} className="m-0" />}
          {decide.isError && <ErrorNote error={decide.error} className="m-0" />}
          {week.data.actions && (
            <ActionList
              actions={week.data.actions}
              suggested={report?.moves}
              onOpen={openPlayer}
              onDecide={(decision) => decide.mutate(decision)}
              deciding={decide.isPending}
              footer={
                ai
                  ? (action, controls) =>
                      action.key && (
                        <WhyThread
                          competition={competition.key}
                          league={league.league_id}
                          action={action}
                          beside={controls}
                        />
                      )
                  : undefined
              }
              aside={
                // Only where a model is configured: a control that cannot
                // work would be an offer and then a refusal.
                ai && (
                  <span className="flex items-center gap-2 normal-case tracking-normal">
                    {judgment.data && !judge.isPending && (
                      <span className="font-normal">judged {moment(judgment.data.answered_at)}</span>
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

          {week.data.opponent ? (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <SideCard side={week.data.mine} label="You" onOpen={openPlayer} />
              <SideCard side={week.data.opponent} label="Opponent" onOpen={openPlayer} />
            </div>
          ) : (
            <LineupCard
              title="Your lineup"
              lineup={week.data.mine?.lineup ?? []}
              bench={week.data.mine?.bench ?? []}
              swaps={week.data.swaps}
              onOpen={openPlayer}
            />
          )}

          {/* Shown beside the lineups when there is an opponent, since the
              swaps then have no card of their own to live in. A competition
              with a to-do list sends none: they are items on it. */}
          {week.data.opponent && week.data.swaps.length > 0 && (
            <Card>
              <Swaps swaps={week.data.swaps} />
            </Card>
          )}

          {week.data.boosts && week.data.boosts.stats.length > 0 && (
            <Card>
              <CardHeader>
                <span>{week.data.boosts.title}</span>
                {week.data.boosts.note && <span>{week.data.boosts.note}</span>}
              </CardHeader>
              <StatGrid stats={week.data.boosts.stats} />
            </Card>
          )}

          {/* Only what a row cannot say for itself: a blank or a double gameweek
              changes what a whole club's players are worth. */}
          {week.data.fixtures.length > 0 && (
            <Card>
              <CardHeader>
                <span>Watch out for</span>
              </CardHeader>
              <StatList stats={week.data.fixtures} className="px-4 py-1" />
            </Card>
          )}

          {!week.data.opponent && (
            <Badge variant="muted" appearance="label">
              No head-to-head fixture this week
            </Badge>
          )}
        </div>
      )}
      {drawer}
    </>
  );
}
