import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Cause, Option, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { Comparing } from "@/components/league/compare";
import { DrawerState, Drawers, comparisonDrawer } from "@/components/league/drawers";
import { LeagueHeader } from "@/components/league/page-header";
import { Icon } from "@/components/ui/icon";
import { Meta } from "@/components/ui/label";
import { ListCard } from "@/components/ui/list";
import { Hint } from "@/components/ui/overlays/hint";
import { CardNote } from "@/components/ui/state";
import { Table, Td, Th } from "@/components/ui/table";
import { Clickable } from "@/lib/clickable";
import { traded } from "@/lib/comparing";
import { percent, percentPoints, signed } from "@/lib/format";
import { GetTrades } from "@/lib/queries/players";
import { AppRoute } from "@/lib/route";
import type { Competition, League, TradeIdea, Trades } from "@/lib/types";
import { cn } from "@/lib/utils";
import { wire } from "@/lib/wire";

/**
 * Half a point — of playoff chance, or of starters' points a week — below
 * which a change is noise and is not tinted either way.
 */
export const NOTICEABLE = 0.5;

/** The same for a figure counted in categories: a tenth of one a week. */
export const NOTICEABLE_CATEGORIES = 0.1;

type Measure = Trades["measure"];

const TradesPanelMessage = UiSchema.TaggedEnum({
  ClickedTrade: { comparing: Comparing },
  RequestedOpenDrawers: { open: DrawerState },
  RequestedCloseDrawers: {},
});

/**
 * The trades worth offering, and the day trading closes where the league's settings name one.
 *
 * The trades that would do most for you, with who to offer each to and why he might say yes.
 *
 * A table, one trade a row, because the trades are compared with each other:
 * what each gives, gets, and does for you, read down a column. Ordered by the
 * server on the figure that matters most where you stand — your playoff chance
 * on the bubble, your points over the rest of the season once that is safe —
 * and that column says so. A trade can cost the regular season for the
 * playoffs; both columns show, so the cost is in view beside the gain. A row
 * opens both sides of its trade side by side.
 *
 * Fetched apart from the squad: each trade is a season played out thousands
 * of times, which is seconds the roster should not wait on.
 */
export const TradesPanel = Html.component({
  name: "TradesPanel",
  props: Schema.Struct({ competition: wire<Competition>(), league: wire<League>(), route: AppRoute }),
  model: Schema.Struct({ drawer: Schema.NullOr(DrawerState) }),
  message: TradesPanelMessage,
  queries: {
    trades: {
      query: GetTrades,
      args: ({ props }) => ({ competition: props.competition.key, league: props.league.league_id }),
    },
  },
}).make({
  init: () => ({ drawer: null }),
  update: {
    ClickedTrade: ($, { comparing }) => $.evolve({ drawer: comparisonDrawer(comparing.ids, comparing) }),
    RequestedOpenDrawers: ($, { open }) => $.evolve({ drawer: open }),
    RequestedCloseDrawers: ($) => $.evolve({ drawer: null }),
  },
  view: (h, model) => {
    const { competition, league } = h.props;
    const result = h.queries.trades;
    const trades = Option.getOrUndefined(AsyncResult.value(result));
    const ideas = trades?.ideas;
    const ranked = trades?.ranked_by;
    const measure = trades?.measure ?? "points";

    // Playoff weeks the platform has not projected yet have no column rather than one of dashes.
    const figures = FIGURES[measure].filter(
      (f) => f.key !== "playoff_points" || ideas?.some((i) => i.playoff_points != null),
    );

    const pricing = priced(ideas ?? []);
    const closes = trades?.deadline ? ` · deadline ${day(trades.deadline)}` : "";

    return h.div.class("contents").children(
      LeagueHeader(h, { competition, league }),
      h.div.class("flex flex-col gap-4 p-5").children(
        ListCard(h, {
          title: "Trades worth offering",
          count: ideas ? `${ideas.length} found${closes}` : undefined,
          loading: AsyncResult.isInitial(result),
          error: AsyncResult.isFailure(result) ? Cause.squash(result.cause) : null,
          children: [
            ideas?.length === 0 && CardNote(h).children("No trades worth offering."),
            ideas !== undefined &&
              ideas.length > 0 &&
              Table(h).children(
                h.thead.children(
                  h.tr.children(
                    Th(h).children("Give"),
                    Th(h).children("Get"),
                    Th(h).children("Partner"),
                    figures.map((f) =>
                      Th(h, "text-right")
                        .key(f.key)
                        .children(
                          Hint(h, {
                            key: `figure-${f.key}`,
                            props: {
                              label: f.key === ranked ? `${f.about}. Best first.` : f.about,
                              side: "left",
                              class: "inline-flex items-center gap-1",
                            },
                            slots: {
                              content: [
                                f.key === ranked &&
                                  h.span
                                    .attrs({ role: "img", "aria-label": "ordered by", class: "inline-flex" })
                                    .children(Icon(h, "arrow-down", { class: "size-3" })),
                                f.label,
                              ],
                            },
                          }),
                        ),
                    ),
                  ),
                ),
                h.tbody.children(
                  ideas.map((idea) => {
                    const key = `${idea.team_id}-${idea.giving.join()}-${idea.receiving.join()}`;
                    const open = traded(idea, (comparing) => TradesPanelMessage.ClickedTrade({ comparing }));

                    return Clickable(h, "tr", open?.())
                      .key(key)
                      .attr(
                        "class",
                        cn(idea.giving_ids.length + idea.receiving_ids.length > 1 && "cursor-pointer hover:bg-muted"),
                      )
                      .children(
                        Td(h).children(Players(h, { key: `${key}-give`, names: idea.giving, pricing })),
                        Td(h).children(
                          Players(h, { key: `${key}-get`, names: idea.receiving, pricing }),
                          idea.pickup && Aside(h).children(`+ add ${idea.pickup}`),
                        ),
                        Td(h).children(
                          h.span.class("block whitespace-nowrap").children(idea.team),
                          Aside(h).children(theirCase(idea, measure)),
                        ),
                        figures.map((f) =>
                          Td(h, cn("whitespace-nowrap text-right", f.key === ranked && "font-medium"))
                            .key(f.key)
                            .children(Figure(h, { idea, figure: f.key, measure })),
                        ),
                      );
                  }),
                ),
              ),
            trades?.pickup && CardNote(h).children(`Two-for-ones free a spot: add ${trades.pickup}`),
          ],
        }),
      ),
      Drawers(h, {
        props: { competition: competition.key, league: league.league_id, open: model.drawer },
        onEmit: {
          RequestedOpen: ({ open }) => TradesPanelMessage.RequestedOpenDrawers({ open }),
          RequestedClose: () => TradesPanelMessage.RequestedCloseDrawers(),
        },
      }),
    );
  },
});

type Figured = Trades["ranked_by"] | "points" | "playoff_points";

/** The figures for you, each a column, with what each measures on hover: points, or categories expected. */
const FIGURES: Record<Measure, { key: Figured; label: string; about: string }[]> = {
  points: [
    { key: "points", label: "Season /wk", about: "Your starters' points a week, rest of the regular season" },
    { key: "playoff_points", label: "Playoffs /wk", about: "Your starters' points a playoff week" },
    {
      key: "total",
      label: "Total",
      about: "Your starters' points, rest of season: playoff weeks weighed by your odds",
    },
    { key: "playoffs_change", label: "Odds", about: "Your playoff chance, and where it ends up" },
  ],
  categories: [
    {
      key: "points",
      label: "Season cats /wk",
      about: "Categories you expect to win a week against each opponent, rest of the regular season",
    },
    {
      key: "playoff_points",
      label: "Playoffs cats /wk",
      about: "Categories you expect to win a playoff week, against the field",
    },
    {
      key: "total",
      label: "Total cats",
      about: "Categories you expect to win, rest of season: playoff weeks weighed by your odds",
    },
    { key: "playoffs_change", label: "Odds", about: "Your playoff chance, and where it ends up" },
  ],
};

/** A quiet second line in a cell. */
function Aside<M>(h: Html.H<M>) {
  return Meta(h, { class: "block whitespace-nowrap" });
}

/** One side of a trade, a player a line, his pricing on hover where it is off his projection. */
function Players<M>(
  h: Html.H<M>,
  { key, names, pricing }: { key: string; names: readonly string[]; pricing: Map<string, string> },
) {
  return names.map((name) => {
    const why = pricing.get(name);

    return h.span
      .key(name)
      .class("block whitespace-nowrap")
      .children(
        why
          ? Hint(h, { key: `${key}-${name}`, props: { label: why, name: `${name}: ${why}`, dotted: true }, slots: { content: name } })
          : name,
      );
  });
}

/** One figure for you; a change is tinted only where it is noticeable, and its sign says it in text too. */
function Figure<M>(h: Html.H<M>, { idea, figure, measure }: { idea: TradeIdea; figure: Figured; measure: Measure }) {
  if (figure === "playoffs_change") {
    const change = idea.playoffs_change * 100;

    return h.span
      .class("contents")
      .children(
        h.span.attr("class", tint(change)).children(percentPoints(idea.playoffs_change)),
        Aside(h).children(`to ${percent(idea.playoffs)}`),
      );
  }

  const value = figure === "points" ? idea.points : figure === "total" ? idea.total : idea.playoff_points;

  if (value == null) return h.span.class("text-muted-foreground").children("—");

  const categories = measure === "categories";

  return h.span
    .attr("class", tint(value, categories ? NOTICEABLE_CATEGORIES : NOTICEABLE))
    .children(signed(value, categories ? 2 : 1));
}

function tint(change: number, noticeable = NOTICEABLE): string {
  return change >= noticeable ? "text-ok" : change <= -noticeable ? "text-warn" : "";
}

/** "25 Feb": a date the server sends as ISO, read as the calendar day it names rather than a UTC midnight. */
export function day(iso: string): string {
  // A date and a time without a zone is local time; a bare date would be UTC, a day early west of it.
  return new Date(`${iso}T00:00`).toLocaleDateString([], { day: "numeric", month: "short" });
}

/**
 * Each player's pricing, by the name a trade lists him under, across the whole list.
 *
 * The server says it once, on the first trade he is in; a hover on any trade
 * he is in should still answer it.
 */
export function priced(ideas: readonly TradeIdea[]): Map<string, string> {
  const lines = ideas.flatMap((idea) => idea.form);
  const named = new Map<string, string>();

  for (const name of ideas.flatMap((idea) => [...idea.giving, ...idea.receiving])) {
    // A trade lists "Matthew Golden (WR)"; his pricing is under "Matthew Golden".
    const line = lines.find((l) => name === l.label || name.startsWith(`${l.label} (`));

    if (line) named.set(name, line.value);
  }

  return named;
}

/**
 * Why the other manager might say yes: out of the race he weighs only worth,
 * and in it, his starters — or in a category league, the categories he
 * expects to take, which every trade offered there raises.
 */
export function theirCase(idea: TradeIdea, measure: Measure = "points"): string {
  if (measure === "categories") return `their cats ${signed(idea.their_points, 2)} /wk`;

  if (idea.their_playoffs < 0.05) return `out of the race, ${percent(idea.their_playoffs)}`;

  return `their starters ${signed(idea.their_points)} /wk`;
}
