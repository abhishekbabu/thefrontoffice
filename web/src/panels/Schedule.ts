import { Html } from "@effect/ui/html";
import { Option, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { LeagueHeader } from "@/components/league/page-header";
import { Badge } from "@/components/ui/badge";
import { Label, Meta } from "@/components/ui/label";
import { ListCard, ListHeading, ListRow } from "@/components/ui/list";
import { Hint } from "@/components/ui/overlays/hint";
import { Empty, QueryState } from "@/components/ui/state";
import { GetSeason } from "@/lib/queries/teams";
import { AppRoute } from "@/lib/route";
import type { Variant } from "@/lib/tone";
import type { Competition, League, ScheduleRow } from "@/lib/types";
import { wire } from "@/lib/wire";

/**
 * Your season, week by week: who you play, how each went, and what else falls in it.
 *
 * Read from the league's schedule, the same answer the League page's table
 * comes from, so the two cannot disagree. The week being played shows its score so far, from the matchup
 * the Matchup page reads.
 */
export const SchedulePanel = Html.component({
  name: "SchedulePanel",
  props: Schema.Struct({ competition: wire<Competition>(), league: wire<League>(), route: AppRoute }),
  model: Schema.Null,
  message: Schema.Never,
  queries: {
    schedule: {
      query: GetSeason,
      args: ({ props }) => ({ competition: props.competition.key, league: props.league.league_id }),
    },
  },
}).make({
  init: () => null,
  update: ($) => $.model,
  view: (h) => {
    const { competition, league } = h.props;
    const season = Option.getOrUndefined(AsyncResult.value(h.queries.schedule))?.season;

    return h.div.class("contents").children(
      LeagueHeader(h, { competition, league }),
      QueryState(h, h.queries.schedule, { lines: 6 }),
      season !== undefined && season.length === 0 && Empty(h, { title: "No head-to-head schedule" }),
      season !== undefined && season.length > 0 && h.div.class("p-5").children(Season(h, { rows: season })),
    );
  },
});

const OUTCOME: Record<NonNullable<ScheduleRow["outcome"]>, { letter: string; variant: Variant }> = {
  won: { letter: "W", variant: "ok" },
  lost: { letter: "L", variant: "fail" },
  drawn: { letter: "D", variant: "muted" },
};

export function Season<M>(h: Html.H<M>, { rows }: { rows: readonly ScheduleRow[] }) {
  return ListCard(h, {
    title: "Your season",
    count: `${rows.length} weeks`,
    children: rows.flatMap((row, i) => [
      // The bracket is a different competition from the weeks before it, so it reads as one.
      row.playoffs && !rows[i - 1]?.playoffs && ListHeading(h).key("playoffs").children("Playoffs"),
      // Read left to right as one sentence: when, against whom, how it went, what else is on.
      // On a phone, when stacks over its dates and the rest wraps beside
      // them: in one line the result ran 125px off the card.
      ListRow(h, { current: row.is_current })
        .key(row.label)
        .children(
          h.span.class("flex w-24 shrink-0 flex-col gap-0.5 sm:contents").children(
            Label(h, { class: "sm:w-24 sm:shrink-0" }).children(row.label),
            Meta(h, { class: "sm:w-32 sm:shrink-0" }).children(row.date),
          ),
          h.span.class("flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 sm:contents").children(
            h.span
              .class("flex w-full min-w-0 items-center gap-2 sm:w-64")
              .children(
                row.opponent
                  ? [h.span.class("truncate").children(row.opponent), Standing(h, row)]
                  : [h.span.class("text-muted-foreground").children(row.detail || "—")],
              ),
            // Won and lost are carried by the letter as well as the color: state
            // in color alone is state a colorblind reader cannot see.
            row.result &&
              Badge(h, {
                variant: row.outcome ? OUTCOME[row.outcome].variant : "muted",
                appearance: "pill",
                class: "shrink-0 tabular-nums",
              }).children(`${row.outcome ? OUTCOME[row.outcome].letter : row.is_current ? "live" : ""} ${row.result}`),
            // Said, not only shaded — the tint is reinforcement.
            row.is_current && Badge(h, { variant: "muted", appearance: "label", class: "shrink-0" }).children("this week"),
            row.marks.map((mark) =>
              Badge(h, { variant: "warn", appearance: "status", class: "shrink-0" }).key(mark).children(mark),
            ),
          ),
        ),
    ]),
  });
}

/**
 * What the row says of the opponent beside their name: the playoff round, or their record.
 *
 * The record is the one they hold now, not the one they held that week, so a
 * week already decided shows none: beside a result it would read as theirs
 * at the time.
 */
function Standing<M>(h: Html.H<M>, row: ScheduleRow) {
  if (!row.detail || (!row.playoffs && row.outcome)) return null;

  const badge = Badge(h, { variant: "muted", appearance: "label", class: "shrink-0 tabular-nums" }).children(row.detail);

  if (row.playoffs) return badge;

  return Hint(h, {
    key: `record-${row.label}`,
    props: { label: "Their record now", name: `Record now ${row.detail}`, class: "shrink-0" },
    slots: { content: badge },
  });
}
