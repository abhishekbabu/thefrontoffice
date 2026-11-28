import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { Badge } from "@/components/ui/badge";
import { Busy } from "@/components/ui/state";
import { traded, type Comparing } from "@/lib/comparing";
import { percentPoints, signed } from "@/lib/format";
import { GetTrades } from "@/lib/queries/players";
import { href } from "@/lib/route";
import type { TradeIdea, Trades } from "@/lib/types";
import { wire } from "@/lib/wire";

/** `RequestedCompare`: open the trade's two sides side by side, as a row on the Trades page does. */
export const BestTradeEvents = UiSchema.TaggedEnum({ RequestedCompare: { comparing: wire<Comparing>() } });

const BestTradeMessage = UiSchema.TaggedEnum({ ClickedTrade: { comparing: wire<Comparing>() } });

/**
 * The best trade the Trades page has, under the deadline item: an item that
 * says only "trade" leaves you to go and find out what. Read from the same
 * query as that page, so it is computed once for both, and linked to it for
 * the rest. The gain shown is the figure that page orders by, so "best"
 * means the same thing in both places. Its absence is said, tersely: no
 * offer is an answer.
 */
export const BestTrade = Html.component({
  name: "BestTrade",
  props: Schema.Struct({ competition: Schema.String, league: Schema.String }),
  model: Schema.Null,
  message: BestTradeMessage,
  events: BestTradeEvents,
  queries: {
    trades: { query: GetTrades, args: ({ props }) => ({ competition: props.competition, league: props.league }) },
  },
  restore: false,
}).make({
  init: () => null,
  update: {
    ClickedTrade: ($, { comparing }) => $.emit(BestTradeEvents.RequestedCompare({ comparing })),
  },
  view: (h) => {
    const result = h.queries.trades;
    const trades = AsyncResult.isSuccess(result) ? result.value : null;
    const best = trades?.ideas[0];
    const said = best && `Best: give ${best.giving.join(" and ")} for ${best.receiving.join(", ")} with ${best.team}`;
    const open = best && traded(best, (comparing) => BestTradeMessage.ClickedTrade({ comparing }))?.();

    return h.div.class("flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]").children(
      AsyncResult.isInitial(result) && Busy(h).children("finding trades…"),
      best &&
        trades && [
          open
            ? h.button
                .attrs({ type: "button", class: "text-left underline-offset-2 hover:underline" })
                .on("click", open)
                .on("keydown", () => undefined)
                .children(said)
            : h.span(said),
          Badge(h, { variant: "ok", appearance: "pill", class: "tabular-nums" }).children(
            gain(best, trades.ranked_by, trades.measure),
          ),
        ],
      trades && !best && h.span.class("text-muted-foreground").children("No trades worth offering."),
      h.a
        .attrs({
          href: href(h.props.competition, h.props.league, "trades"),
          class: "font-mono text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground",
        })
        .children("All trades"),
    );
  },
});

/**
 * What a trade gains you on the figure the list is ranked by, in words: '+21.4 pts rest of season',
 * '+1.25 cats rest of season', 'playoff odds +4.0 pts'.
 */
export function gain(idea: TradeIdea, ranked: Trades["ranked_by"], measure: Trades["measure"] = "points"): string {
  if (ranked === "playoffs_change") return `playoff odds ${percentPoints(idea.playoffs_change)}`;

  if (measure === "categories") return `${signed(idea.total, 2)} cats rest of season`;

  return `${signed(idea.total)} pts rest of season`;
}
