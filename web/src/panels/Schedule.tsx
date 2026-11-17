import { Fragment } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Competition, type League, type LeagueSchedule, type ScheduleRow } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { Variant } from "@/lib/tone";
import { StatStrip } from "@/components/ui/stat";
import { Badge } from "@/components/ui/badge";
import { ListCard, ListRow } from "@/components/ui/list";
import { Empty, QueryState } from "@/components/ui/state";
import { LeagueHeader } from "@/components/ui/page-header";
import { Label } from "@/components/ui/label";

/**
 * Your season, week by week: who you play, how each went, and what else falls in it.
 *
 * Read from the league's schedule, the same answer the League page's table
 * and header come from, so the record above and the results below cannot
 * disagree. The week being played shows its score so far, from the matchup
 * the Matchup page reads.
 */
export function SchedulePanel({ competition, league }: { competition: Competition; league: League }) {
  const schedule = useQuery<LeagueSchedule, Error>({
    queryKey: keys.schedule(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).schedule,
  });

  return (
    <>
      <LeagueHeader league={league} />
      <StatStrip stats={schedule.data?.headline ?? []} />
      <QueryState query={schedule} lines={6} />
      {schedule.data && schedule.data.season.length === 0 && (
        <Empty title="No season to show" detail="This league plays no head-to-head schedule." />
      )}
      {schedule.data && schedule.data.season.length > 0 && (
        <div className="p-5">
          <Season rows={schedule.data.season} />
        </div>
      )}
    </>
  );
}

const OUTCOME: Record<NonNullable<ScheduleRow["outcome"]>, { letter: string; variant: Variant }> = {
  won: { letter: "W", variant: "ok" },
  lost: { letter: "L", variant: "fail" },
  drawn: { letter: "D", variant: "muted" },
};

export function Season({ rows }: { rows: ScheduleRow[] }) {
  return (
    <ListCard title="Your season" count={`${rows.length} weeks`}>
      {rows.map((row, i) => (
        <Fragment key={row.label}>
          {/* The bracket is a different competition from the weeks before it, so it reads as one. */}
          {row.playoffs && !rows[i - 1]?.playoffs && (
            <Label as="div" className="border-t border-border bg-muted px-4 py-1.5">
              Playoffs
            </Label>
          )}
          <ListRow current={row.is_current}>
            <Label className="w-24 shrink-0">{row.label}</Label>
            <span className="w-32 shrink-0 font-mono text-[11px] text-muted-foreground">{row.date}</span>
            <span className="flex min-w-0 flex-1 items-center gap-2">
              {row.opponent ? (
                <>
                  <span className="truncate">{row.opponent}</span>
                  {row.detail && (
                    <Badge variant="muted" appearance="label" className="shrink-0 tabular-nums">
                      {row.detail}
                    </Badge>
                  )}
                </>
              ) : (
                <span className="text-muted-foreground">{row.detail || "—"}</span>
              )}
            </span>
            {/* Said, not only shaded — the tint is reinforcement. */}
            {row.is_current && (
              <Badge variant="muted" appearance="label" className="shrink-0">
                this week
              </Badge>
            )}
            {row.marks.map((mark) => (
              <Badge key={mark} variant="warn" appearance="status" className="shrink-0">
                {mark}
              </Badge>
            ))}
            {/* Won and lost are carried by the letter as well as the color: state
                in color alone is state a colorblind reader cannot see. */}
            {row.result && (
              <Badge
                variant={row.outcome ? OUTCOME[row.outcome].variant : "muted"}
                appearance="pill"
                className="tabular-nums"
              >
                {row.outcome ? OUTCOME[row.outcome].letter : row.is_current && "live"} {row.result}
              </Badge>
            )}
          </ListRow>
        </Fragment>
      ))}
    </ListCard>
  );
}
