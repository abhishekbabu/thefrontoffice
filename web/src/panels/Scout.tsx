import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { api, type Action, type ItemDecision, type ScoutReport, type Remembered, type League, type Competition, type Summary } from "@/lib/api";
import { ActionList, WhyThread } from "@/components/ui/actions";
import { IconButton } from "@/components/ui/icon-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Loading } from "@/components/ui/state";
import { StatStrip } from "@/components/ui/stat";
import { LineupCard, SideCard } from "@/components/ui/lineup";
import { usePlayerDrawer } from "@/components/ui/player";
import { cn } from "@/lib/utils";
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

  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities });
  const ai = capabilities.data?.ai ?? false;

  const week = useQuery<Summary, Error>({
    queryKey: ["summary", competition.key, league.league_id],
    queryFn: () => api.summary(competition.key, league.league_id),
  });

  // The last judgment, read without asking the model anything: judging is a
  // click, and a reload should not throw the answer away.
  const judgmentKey = ["judgment", competition.key, league.league_id];
  const judgment = useQuery<Remembered<ScoutReport> | null, Error>({
    queryKey: judgmentKey,
    queryFn: () => api.judgment(competition.key, league.league_id),
    enabled: ai && Boolean(week.data?.actions),
  });
  const queryClient = useQueryClient();
  const judge = useMutation<ScoutReport, Error>({
    mutationFn: () => api.scout(competition.key, league.league_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: judgmentKey }),
  });
  const report = judgment.data?.answer;
  // Shown at once, then confirmed: re-reading the week takes a second or two,
  // which is too long for a row to sit there after it was dismissed. The
  // re-read still happens, and a failed save puts the row back.
  const summaryKey = ["summary", competition.key, league.league_id];
  const decide = useMutation<unknown, Error, ItemDecision, { before?: Summary }>({
    mutationFn: (decision) => api.decide(competition.key, league.league_id, decision),
    onMutate: async (decision) => {
      await queryClient.cancelQueries({ queryKey: summaryKey });
      const before = queryClient.getQueryData<Summary>(summaryKey);
      if (before?.actions) {
        queryClient.setQueryData<Summary>(summaryKey, {
          ...before,
          actions: before.actions.map((action) => (action.key === decision.key ? decided(action, decision) : action)),
        });
      }
      return { before };
    },
    onError: (_error, _decision, context) => {
      if (context?.before) queryClient.setQueryData(summaryKey, context.before);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: summaryKey }),
  });

  return (
    <>
      {/* The week is what this page is about, so it belongs in the header
          rather than a row down among the figures. */}
      <LeagueHeader league={league} meta={[week.data?.window, league.detail].filter(Boolean).join(" · ")} />
      <StatStrip stats={week.data?.headline ?? []} />

      {week.isLoading && <Loading lines={4} />}
      {week.isError && <ErrorNote error={week.error} />}

      {week.data && (
        <div className="flex flex-col gap-4 p-5">
          {judge.isError && <ErrorNote error={judge.error} />}
          {decide.isError && <ErrorNote error={decide.error} />}
          {week.data.actions && (
            <ActionList
              actions={week.data.actions}
              judged={report?.tasks}
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
                      <span className="font-normal">judged {judgedAt(judgment.data.answered_at)}</span>
                    )}
                    {judge.isPending && <span className="font-normal">judging…</span>}
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
              swaps={week.data.actions ? [] : week.data.swaps}
              onOpen={openPlayer}
            />
          )}

          {/* Shown beside the lineups when there is an opponent, since the
              swaps then have no card of their own to live in. */}
          {!week.data.actions && week.data.opponent && week.data.swaps.length > 0 && (
            <Card>
              <CardHeader>
                <span>Changes the projections imply</span>
              </CardHeader>
              {week.data.swaps.map((swap) => (
                <div
                  key={swap.start}
                  className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-t border-border px-4 py-2.5 text-[13px] first:border-t-0"
                >
                  <span className="font-medium">{swap.start}</span>
                  <span className="text-muted-foreground">for {swap.out || "an empty place"}</span>
                  <span className="ml-auto font-mono text-[12px] text-ok">{swap.gain}</span>
                </div>
              ))}
            </Card>
          )}

          {week.data.boosts && week.data.boosts.stats.length > 0 && (
            <Card>
              <CardHeader>
                <span>{week.data.boosts.title}</span>
                <span>
                  {week.data.boosts.stats.filter((s) => s.tone === "good").length} available
                </span>
              </CardHeader>
              {/* A grid rather than a strip: these are four parallel answers to
                  the same question, and reading down a column beats hunting. */}
              <div className="grid grid-cols-2 gap-x-4 px-4 py-1 sm:grid-cols-4">
                {week.data.boosts.stats.map((boost) => (
                  <div key={boost.label} className="flex flex-col gap-0.5 py-2.5">
                    <span className="truncate font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                      {boost.label}
                    </span>
                    <span
                      className={cn(
                        "truncate text-[13px]",
                        boost.tone === "good" && "font-medium text-ok",
                        boost.tone === "warning" && "text-warn",
                        boost.tone === "neutral" && "text-muted-foreground",
                      )}
                    >
                      {boost.value}
                    </span>
                  </div>
                ))}
              </div>
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

/** "14:05" today, "Thu 14:05" before — when the verdicts were written, in the viewer's own zone. */
function judgedAt(iso: string): string {
  const when = new Date(iso);
  const time = when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return when.toDateString() === new Date().toDateString()
    ? time
    : `${when.toLocaleDateString([], { weekday: "short" })} ${time}`;
}

/** An item as it will read once `decision` is kept — what the server will say, said early. */
function decided(action: Action, decision: ItemDecision): Action {
  if (decision.decision === "dismiss") return { ...action, hidden: "dismissed", resurfaced: false };
  if (decision.decision === "snooze") return { ...action, hidden: "snoozed", snoozed_until: decision.until };
  return { ...action, hidden: null, snoozed_until: null, resurfaced: false };
}
