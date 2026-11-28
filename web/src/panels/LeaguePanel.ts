import { Command, Router, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Option, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { LeagueHeader } from "@/components/league/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Meta } from "@/components/ui/label";
import { Empty, QueryState } from "@/components/ui/state";
import { Table, Td, Th } from "@/components/ui/table";
import { Clickable } from "@/lib/clickable";
import { GetSeason } from "@/lib/queries/teams";
import { AppRoute } from "@/lib/route";
import type { Competition, League, LeagueSchedule } from "@/lib/types";
import { cn } from "@/lib/utils";
import { wire } from "@/lib/wire";

const LeaguePanelMessage = UiSchema.TaggedEnum({ ClickedTeam: { team: Schema.String } });

/**
 * The league table: who, then how they stand — record, points for and
 * against, playoff chance — then what they have left to spend: FAAB and
 * waiver order. A row opens that team's roster.
 */
export const LeaguePanel = Html.component({
  name: "LeaguePanel",
  props: Schema.Struct({ competition: wire<Competition>(), league: wire<League>(), route: AppRoute }),
  model: Schema.Null,
  message: LeaguePanelMessage,
  queries: {
    schedule: {
      query: GetSeason,
      args: ({ props }) => ({ competition: props.competition.key, league: props.league.league_id }),
    },
  },
}).make({
  init: () => null,
  update: {
    ClickedTeam: ($, { team }) =>
      $.run(
        Router.push(
          AppRoute,
          AppRoute.View({
            params: { competition: $.props.competition.key, league: $.props.league.league_id, view: "rosters" },
            search: { team },
          }),
        ).pipe(Command.asNoop),
      ),
  },
  view: (h) => {
    const { competition, league } = h.props;
    const standings = Option.getOrUndefined(AsyncResult.value(h.queries.schedule))?.standings;

    return h.div.class("contents").children(
      LeagueHeader(h, { competition, league }),
      QueryState(h, h.queries.schedule, { lines: 6 }),
      standings !== undefined && standings.length === 0 && Empty(h, { title: "No table" }),
      standings !== undefined &&
        standings.length > 0 &&
        h.div.class("p-5").children(Standings(h, { rows: standings, onOpen: (team) => LeaguePanelMessage.ClickedTeam({ team }) })),
    );
  },
});

function Standings<M>(
  h: Html.H<M>,
  { rows, onOpen }: { rows: LeagueSchedule["standings"]; onOpen: (teamId: string) => M },
) {
  // Only the columns this league fills: FPL has no waiver budget, and a league
  // that is not simulated has no playoff chance.
  const has = (key: "record" | "points_against" | "waiver_budget" | "waiver_order" | "playoffs") =>
    rows.some((row) => row[key]);

  return Card(h).children(
    CardHeader(h).children(h.span("Table"), h.span(`${rows.length} teams`)),
    Table(h).children(
      h.thead.children(
        h.tr.children(
          Th(h, "w-8 text-right").children("#"),
          Th(h).children("Team"),
          has("record") && Th(h, "text-right").children("Record"),
          Th(h, "text-right").children(has("points_against") ? "PF" : "Pts"),
          has("points_against") && Th(h, "text-right").children("PA"),
          has("playoffs") && Th(h, "text-right").children("Playoffs"),
          has("waiver_budget") && Th(h, "text-right").children("FAAB"),
          has("waiver_order") && Th(h, "text-right").children("Waiver"),
        ),
      ),
      h.tbody.children(
        rows.map((row) =>
          Clickable(h, "tr", row.team_id ? onOpen(row.team_id) : undefined)
            .key(`${row.rank}-${row.name}`)
            .attr("class", cn(row.team_id && "cursor-pointer hover:bg-muted", row.is_mine && "bg-muted/60"))
            .children(
              Td(h, "text-right font-mono text-muted-foreground").children(String(row.rank)),
              Td(h).children(
                h.span.class("flex min-w-0 items-center gap-2").children(
                  h.span.class("truncate").children(row.name),
                  row.is_mine && Badge(h, { variant: "muted", appearance: "label", class: "shrink-0" }).children("you"),
                  row.detail && Meta(h, { class: "hidden truncate sm:block" }).children(row.detail),
                ),
              ),
              has("record") && Td(h, "text-right font-mono").children(row.record),
              Td(h, "text-right font-mono").children(row.points),
              has("points_against") && Td(h, "text-right font-mono").children(row.points_against),
              has("playoffs") && Td(h, "text-right font-mono text-muted-foreground").children(row.playoffs),
              has("waiver_budget") && Td(h, "text-right font-mono").children(row.waiver_budget),
              has("waiver_order") && Td(h, "text-right font-mono").children(row.waiver_order),
            ),
        ),
      ),
    ),
  );
}
