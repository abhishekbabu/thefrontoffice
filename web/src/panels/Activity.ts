import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Option, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { DrawerState, Drawers, moveDrawer } from "@/components/league/drawers";
import { MoveRow } from "@/components/league/move";
import { LeagueHeader } from "@/components/league/page-header";
import { ListCard } from "@/components/ui/list";
import { Empty, QueryState } from "@/components/ui/state";
import { GetSeason } from "@/lib/queries/teams";
import { AppRoute } from "@/lib/route";
import type { ActivityRow, Competition, League } from "@/lib/types";
import { wire } from "@/lib/wire";

const ActivityPanelMessage = UiSchema.TaggedEnum({
  ClickedMove: { move: wire<ActivityRow>() },
  RequestedOpenDrawers: { open: DrawerState },
  RequestedCloseDrawers: {},
});

/**
 * What the league did lately, newest first; a row opens the move in full.
 *
 * The row says it in one line, which is all a scan needs. The move itself
 * names each player and whose roster took him. A player there opens his page,
 * and his Back link returns to the move (`Drawers`).
 */
export const ActivityPanel = Html.component({
  name: "ActivityPanel",
  props: Schema.Struct({ competition: wire<Competition>(), league: wire<League>(), route: AppRoute }),
  model: Schema.Struct({ drawer: Schema.NullOr(DrawerState) }),
  message: ActivityPanelMessage,
  queries: {
    schedule: {
      query: GetSeason,
      args: ({ props }) => ({ competition: props.competition.key, league: props.league.league_id }),
    },
  },
}).make({
  init: () => ({ drawer: null }),
  update: {
    ClickedMove: ($, { move }) => $.evolve({ drawer: moveDrawer(move) }),
    RequestedOpenDrawers: ($, { open }) => $.evolve({ drawer: open }),
    RequestedCloseDrawers: ($) => $.evolve({ drawer: null }),
  },
  view: (h, model) => {
    const { competition, league } = h.props;
    const rows = Option.getOrUndefined(AsyncResult.value(h.queries.schedule))?.activity;

    return h.div.class("contents").children(
      LeagueHeader(h, { competition, league }),
      QueryState(h, h.queries.schedule, { lines: 6 }),
      rows !== undefined && rows.length === 0 && Empty(h, { title: "No activity" }),
      rows !== undefined &&
        rows.length > 0 &&
        h.div.class("p-5").children(
          ListCard(h, {
            title: "Recent activity",
            count: `${rows.length} moves`,
            children: rows.map((row, i) =>
              MoveRow(h, { move: row, onOpen: ActivityPanelMessage.ClickedMove({ move: row }) }).key(`${row.when}-${i}`),
            ),
          }),
        ),
      Drawers(h, {
        props: { competition: competition.key, league: league.league_id, open: model.drawer },
        onEmit: {
          RequestedOpen: ({ open }) => ActivityPanelMessage.RequestedOpenDrawers({ open }),
          RequestedClose: () => ActivityPanelMessage.RequestedCloseDrawers(),
        },
      }),
    );
  },
});
