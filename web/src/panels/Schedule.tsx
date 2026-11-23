import { Fragment } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Competition, type League, type LeagueSchedule, type ScheduleRow } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { Variant } from "@/lib/tone";
import { Badge } from "@/components/ui/badge";
import { ListCard, ListHeading, ListRow } from "@/components/ui/list";
import { Hint } from "@/components/ui/tooltip";
import { Empty, QueryState } from "@/components/ui/state";
import { LeagueHeader } from "@/components/league/page-header";
import { Label, Meta } from "@/components/ui/label";

/**
 * Your season, week by week: who you play, how each went, and what else falls in it.
 *
 * Read from the league's schedule, the same answer the League page's table
 * comes from, so the two cannot disagree. The week being played shows its score so far, from the matchup
 * the Matchup page reads.
 */
export function SchedulePanel({ competition, league }: { competition: Competition; league: League }) {
  const schedule = useQuery<LeagueSchedule, Error>({
    queryKey: keys.season(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).season,
  });

  return (
    <>
      <LeagueHeader league={league} />
      <QueryState query={schedule} lines={6} />
      {schedule.data && schedule.data.season.length === 0 && (
        <Empty title="No head-to-head schedule" />
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
            <ListHeading>Playoffs</ListHeading>
          )}
          {/* Read left to right as one sentence: when, against whom, how it went, what else is on. */}
          {/* On a phone, when stacks over its dates and the rest wraps beside
              them: in one line the result ran 125px off the card. */}
          <ListRow current={row.is_current}>
            <span className="flex w-24 shrink-0 flex-col gap-0.5 sm:contents">
              <Label className="sm:w-24 sm:shrink-0">{row.label}</Label>
              <Meta className="sm:w-32 sm:shrink-0">{row.date}</Meta>
            </span>
            <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 sm:contents">
            <span className="flex w-full min-w-0 items-center gap-2 sm:w-64">
              {row.opponent ? (
                <>
                  <span className="truncate">{row.opponent}</span>
                  <Standing row={row} />
                </>
              ) : (
                <span className="text-muted-foreground">{row.detail || "—"}</span>
              )}
            </span>
            {/* Won and lost are carried by the letter as well as the color: state
                in color alone is state a colorblind reader cannot see. */}
            {row.result && (
              <Badge
                variant={row.outcome ? OUTCOME[row.outcome].variant : "muted"}
                appearance="pill"
                className="shrink-0 tabular-nums"
              >
                {row.outcome ? OUTCOME[row.outcome].letter : row.is_current && "live"} {row.result}
              </Badge>
            )}
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
            </span>
          </ListRow>
        </Fragment>
      ))}
    </ListCard>
  );
}

/**
 * What the row says of the opponent beside their name: the playoff round, or their record.
 *
 * The record is the one they hold now, not the one they held that week, so a
 * week already decided shows none: beside a result it would read as theirs
 * at the time.
 */
function Standing({ row }: { row: ScheduleRow }) {
  if (!row.detail || (!row.playoffs && row.outcome)) return null;
  const badge = (
    <Badge variant="muted" appearance="label" className="shrink-0 tabular-nums">
      {row.detail}
    </Badge>
  );
  if (row.playoffs) return badge;
  return (
    <Hint label="Their record now" name={`Record now ${row.detail}`} className="shrink-0">
      {badge}
    </Hint>
  );
}
