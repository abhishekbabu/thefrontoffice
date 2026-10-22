import { useMutation } from "@tanstack/react-query";
import { api, type Analysis, type League, type Competition, type Move } from "@/lib/api";
import { Play, RotateCw } from "lucide-react";
import { IconButton } from "@/components/ui/icon-button";
import { Empty, Working } from "@/components/ui/state";
import { Card, CardHeader } from "@/components/ui/card";
import { Badge, Chips } from "@/components/ui/badge";
import { Chat } from "@/components/ui/chat";
import { ErrorNote } from "@/components/ui/error-note";
import { PageHeader } from "@/components/ui/page-header";
import { moveTone } from "@/lib/tone";
import { ActionList } from "@/components/ui/actions";
import { usePlayerDrawer } from "@/components/ui/player";
import { splitMetric } from "@/lib/metric";

/**
 * The analysis, on its own.
 *
 * Split from the week because the two answer different questions and are read
 * at different moments: the week is a glance before a deadline, this is a
 * considered opinion that costs a model call to produce.
 */
export function ReportPanel({ competition, league }: { competition: Competition; league: League }) {
  const { openPlayer, drawer } = usePlayerDrawer(competition, league);
  const run = useMutation<Analysis, Error>({
    mutationFn: () => api.scout(competition.key, league.league_id),
  });

  return (
    <>
      <PageHeader title="Report" meta={league.name}>
        <IconButton
          label={run.isPending ? "Building the report" : run.data ? "Run again" : "Run report"}
          variant="primary"
          icon={run.data ? <RotateCw /> : <Play />}
          onClick={() => run.mutate()}
          disabled={run.isPending}
        />
      </PageHeader>

      {run.isError && <ErrorNote error={run.error} />}

      {/* A spinner rather than a placeholder: this is work someone started and
          is waiting on, and a skeleton implies something is already arriving. */}
      {run.isPending && <Working label="Reading the league, then asking the model…" />}

      {!run.data && !run.isPending && !run.isError && (
        <Empty
          title="No report yet"
          detail="Reads your league as it stands, works out what has an exact answer — the best legal lineup, what a transfer costs, how many games are left — and asks the model only for the judgement."
        />
      )}

      {run.data && (
        <div className="flex flex-col gap-4 p-5">
          {/* The week's own list first, judged: these are the moves somebody
              is already looking at, and the verdict is what they came for. */}
          {run.data.report.tasks.length > 0 && <ActionList actions={run.data.report.tasks} onOpen={openPlayer} />}

          <Card>
            <CardHeader>
              <span>{run.data.report.tasks.length > 0 ? "Also worth doing" : "What this week turns on"}</span>
              <span>
                {run.data.report.moves.length} {run.data.report.moves.length === 1 ? "move" : "moves"}
              </span>
            </CardHeader>
            <div className="p-4 pb-3">
              <p className="max-w-[62ch] text-[14.5px] leading-relaxed">{run.data.report.situation}</p>
              <Chips items={run.data.report.focus} className="mt-3" />
            </div>

            {run.data.report.moves.map((move, i) => (
              <MoveRow key={`${move.player}-${i}`} move={move} />
            ))}

            {run.data.report.moves.length === 0 && (
              <p className="border-t border-border px-4 py-6 text-center text-[13.5px] text-muted-foreground">
                {run.data.report.tasks.length > 0 ? "Nothing beyond the to-do list." : "No moves worth making this week."}
              </p>
            )}

            <div className="m-4 rounded-md border border-accent-foreground/25 bg-accent-foreground/8 px-3.5 py-2.5 text-[14px] leading-relaxed">
              {run.data.report.strategy}
            </div>
          </Card>

          <Chat chatId={run.data.chat_id} />
        </div>
      )}
      {drawer}
    </>
  );
}

/**
 * One recommendation.
 *
 * Three columns rather than a stack: the action reads as a chip on the left,
 * the reasoning takes the middle at prose width, and the number is right-aligned
 * so the figures form a column you scan down instead of hunting for.
 */
function MoveRow({ move }: { move: Move }) {
  return (
    <div className="grid grid-cols-[5.5rem_minmax(0,1fr)_auto] items-start gap-4 border-t border-border px-4 py-3.5">
      <Badge variant={moveTone(move.action)} appearance="pill">
        {move.action}
      </Badge>

      <div className="min-w-0">
        <div className="font-display text-base font-semibold leading-snug tracking-tight">{move.player}</div>
        <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">
          {[move.position, move.team].filter(Boolean).join(" · ")}
        </div>
        <p className="mt-1.5 max-w-[54ch] text-[13.5px] leading-relaxed text-muted-foreground">{move.rationale}</p>
        {move.replaces && (
          <div className="mt-2 rounded-md bg-muted px-2.5 py-1.5 text-[12.5px] text-muted-foreground">
            <b className="font-semibold text-foreground">{move.replaces}</b>
            {move.replaces_rationale && ` · ${move.replaces_rationale}`}
          </div>
        )}
      </div>

      <MetricValue metric={move.metric} />
    </div>
  );
}

function MetricValue({ metric }: { metric: string }) {
  const parsed = splitMetric(metric);
  if (parsed.figure === null) {
    return <div className="max-w-[9rem] text-right font-mono text-[11px] text-muted-foreground">{parsed.text}</div>;
  }
  return (
    <div className="text-right">
      <div className="font-display text-[19px] font-semibold tracking-tight tabular-nums text-ok">{parsed.figure}</div>
      {parsed.unit && (
        // Written by the model and often a phrase rather than a unit —
        // "proj pts, +4.1 over Smith". Uppercasing and letter-spacing that
        // makes a long one harder to read, not more label-like.
        <div className="mt-0.5 max-w-[11rem] font-mono text-[10px] leading-snug text-muted-foreground">
          {parsed.unit}
        </div>
      )}
    </div>
  );
}
