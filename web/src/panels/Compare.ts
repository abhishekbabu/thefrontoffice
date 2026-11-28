import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Option, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { ComparisonGrid } from "@/components/league/compare";
import { CompareProvider, CompareProviderMessage } from "@/components/league/compare-provider";
import { DrawerState, Drawers, playerDrawer } from "@/components/league/drawers";
import { LeagueHeader } from "@/components/league/page-header";
import { Card, CardHeader } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/controls/input";
import { Icon } from "@/components/ui/icon";
import { Meta } from "@/components/ui/label";
import { ListRow } from "@/components/ui/list";
import { Empty, QueryState } from "@/components/ui/state";
import { MAX_COMPARED, scopeOf } from "@/lib/compare";
import { GetCaptureStatus } from "@/lib/queries/app";
import { GetComparison, SearchPlayers } from "@/lib/queries/players";
import { AppRoute } from "@/lib/route";
import type { Competition, League } from "@/lib/types";
import { wire } from "@/lib/wire";

const ComparePanelMessage = UiSchema.TaggedEnum({
  PickedFinderPlayer: { id: Schema.String },
  RequestedOpenGridPlayer: { id: Schema.String },
  RequestedRemoveGridPlayer: { id: Schema.String },
  RequestedOpenDrawers: { open: DrawerState },
  RequestedCloseDrawers: {},
});

/**
 * Up to four players side by side.
 *
 * Added from any player's drawer, from a move in the league's activity, or by
 * name here where the competition can find players by name. The list is the
 * one every page shares (`CompareProvider`); without one above, nobody is
 * compared.
 */
export const ComparePanel = Html.component({
  name: "ComparePanel",
  props: Schema.Struct({ competition: wire<Competition>(), league: wire<League>(), route: AppRoute }),
  model: Schema.Struct({ drawer: Schema.NullOr(DrawerState) }),
  message: ComparePanelMessage,
  reads: { compare: { owner: CompareProvider, optional: true } },
}).make({
  init: () => ({ drawer: null }),
  update: ($, message) => {
    const scope = scopeOf($.props.competition.key, $.props.league.league_id);

    return ComparePanelMessage.match(message, {
      PickedFinderPlayer: ({ id }) => $.send(CompareProvider, CompareProviderMessage.RequestedAdd({ scope, id })),
      RequestedRemoveGridPlayer: ({ id }) => $.send(CompareProvider, CompareProviderMessage.RequestedRemove({ scope, id })),
      RequestedOpenGridPlayer: ({ id }) => $.evolve({ drawer: playerDrawer(id) }),
      RequestedOpenDrawers: ({ open }) => $.evolve({ drawer: open }),
      RequestedCloseDrawers: () => $.evolve({ drawer: null }),
    });
  },
  view: (h, model) => {
    const { competition, league } = h.props;
    const ids = h.reads.compare?.[scopeOf(competition.key, league.league_id)] ?? [];

    return h.div.class("contents").children(
      LeagueHeader(h, { competition, league }),
      h.div.class("flex flex-col gap-4 p-5").children(
        competition.searches_players &&
          ids.length < MAX_COMPARED &&
          Finder(h, {
            props: { competition, league, exclude: ids },
            onEmit: { Picked: ({ id }) => ComparePanelMessage.PickedFinderPlayer({ id }) },
          }),
        ids.length === 0
          ? Empty(h, {
              title: "Nobody to compare",
              detail: `Add up to ${MAX_COMPARED} players${competition.searches_players ? " above, or" : ""} from any player's page.`,
            })
          : Grid(h, {
              props: { competition: competition.key, league: league.league_id, ids },
              onEmit: {
                RequestedOpen: ({ id }) => ComparePanelMessage.RequestedOpenGridPlayer({ id }),
                RequestedRemove: ({ id }) => ComparePanelMessage.RequestedRemoveGridPlayer({ id }),
              },
            }),
      ),
      Drawers(h, {
        props: { competition: competition.key, league: league.league_id, open: model.drawer },
        onEmit: {
          RequestedOpen: ({ open }) => ComparePanelMessage.RequestedOpenDrawers({ open }),
          RequestedClose: () => ComparePanelMessage.RequestedCloseDrawers(),
        },
      }),
    );
  },
});

const GridMessage = UiSchema.TaggedEnum({
  ClickedPlayer: { id: Schema.String },
  ClickedRemove: { id: Schema.String },
});

const GridEvents = UiSchema.TaggedEnum({
  RequestedOpen: { id: Schema.String },
  RequestedRemove: { id: Schema.String },
});

/** The grid in a card, a column a player, each removable from the list. */
const Grid = Html.component({
  name: "Grid",
  props: Schema.Struct({ competition: Schema.String, league: Schema.String, ids: Schema.Array(Schema.String) }),
  model: Schema.Null,
  message: GridMessage,
  events: GridEvents,
  queries: {
    comparison: {
      query: GetComparison,
      args: ({ props }) => ({ competition: props.competition, league: props.league, ids: props.ids }),
    },
  },
}).make({
  init: () => null,
  update: {
    ClickedPlayer: ($, { id }) => $.emit(GridEvents.RequestedOpen({ id })),
    ClickedRemove: ($, { id }) => $.emit(GridEvents.RequestedRemove({ id })),
  },
  view: (h) => {
    const comparison = Option.getOrUndefined(AsyncResult.value(h.queries.comparison));

    return h.div.class("contents").children(
      QueryState(h, h.queries.comparison, { lines: 6 }),
      comparison &&
        Card(h, "overflow-x-auto").children(
          CardHeader(h).children(h.span("Compare"), h.span(`${comparison.players.length} of ${MAX_COMPARED}`)),
          ComparisonGrid(h, {
            comparison,
            onOpen: (id) => GridMessage.ClickedPlayer({ id }),
            onRemove: (id) => GridMessage.ClickedRemove({ id }),
          }),
        ),
    );
  },
});

const FinderMessage = UiSchema.TaggedEnum({
  UpdatedSearch: { value: Schema.String },
  ClickedPlayer: { id: Schema.String },
});

const FinderEvents = UiSchema.TaggedEnum({ Picked: { id: Schema.String } });

/** Find a player by name and add him; the ones already compared are not offered again. */
const Finder = Html.component({
  name: "Finder",
  props: Schema.Struct({ competition: wire<Competition>(), league: wire<League>(), exclude: Schema.Array(Schema.String) }),
  model: Schema.Struct({ search: Schema.String }),
  message: FinderMessage,
  events: FinderEvents,
  queries: {
    found: {
      query: SearchPlayers,
      args: ({ props, model }) => {
        const search = model.search.trim();

        return search.length >= 2
          ? { competition: props.competition.key, league: props.league.league_id, search }
          : undefined;
      },
      // A list for what was typed before reads as the answer to what is typed now.
      dropPrevious: true,
    },
    // Read from a browser sync, only the players it carried can be found: say so once a search is under way.
    sync: {
      query: GetCaptureStatus,
      args: ({ props }) => (props.competition.syncs ? { platform: props.competition.platform } : undefined),
    },
  },
}).make({
  init: () => ({ search: "" }),
  update: {
    UpdatedSearch: ($, { value }) => $.evolve({ search: value }),
    ClickedPlayer: ($, { id }) => $.evolve({ search: "" }).emit(FinderEvents.Picked({ id })),
  },
  view: (h, model) => {
    const found = Option.getOrUndefined(AsyncResult.value(h.queries.found)) ?? [];
    const synced = Option.getOrUndefined(AsyncResult.value(h.queries.sync))?.active === true;
    const offered = found.filter((p) => !h.props.exclude.includes(p.player_id));

    return Card(h).children(
      h.div.class("px-4 py-3").children(
        SearchInput(h)
          .attrs({ placeholder: "Add a player", "aria-label": "Find a player to compare" })
          .value(model.search)
          .on("input", ({ value }) => FinderMessage.UpdatedSearch({ value })),
      ),
      synced &&
        model.search.trim().length >= 2 &&
        Meta(h, { as: "p", class: "px-4 pb-2" }).children("Synced players only: rosters and the top of the wire."),
      offered.map((p) =>
        ListRow(h, { onClick: FinderMessage.ClickedPlayer({ id: p.player_id }) })
          .key(p.player_id)
          .children(
            Icon(h, "plus", { class: "size-3.5 shrink-0 text-muted-foreground" }),
            h.span.class("min-w-0 flex-1 truncate").children(p.name),
            Meta(h, { class: "shrink-0" }).children(p.detail),
          ),
      ),
    );
  },
});
