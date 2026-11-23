import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { type Competition, type League, type TradeIdea, type Trades } from "@/lib/types";
import { keys } from "@/lib/queries";
import { percentPoints, signed } from "@/lib/format";
import { href } from "@/lib/route";
import { traded, type Comparing } from "@/lib/comparing";
import { Badge } from "@/components/ui/badge";
import { Busy } from "@/components/ui/state";

/**
 * The best trade the Trades page has, under the deadline item: an item that
 * says only "trade" leaves you to go and find out what. Read from the same
 * query as that page, so it is computed once for both, and linked to it for
 * the rest. The gain shown is the figure that page orders by, so "best"
 * means the same thing in both places. Its absence is said, tersely: no
 * offer is an answer.
 */
export function BestTrade({
  competition,
  league,
  onCompare,
}: {
  competition: Competition;
  league: League;
  /** Opens the trade's two sides side by side, as a row on the Trades page does. */
  onCompare?: (comparing: Comparing) => void;
}) {
  const trades = useQuery<Trades, Error>({
    queryKey: keys.trades(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).trades,
  });

  const best = trades.data?.ideas[0];
  const said = best && `Best: give ${best.giving.join(" and ")} for ${best.receiving.join(", ")} with ${best.team}`;
  const open = best && onCompare ? traded(best, onCompare) : undefined;

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]">
      {trades.isLoading && <Busy>finding trades…</Busy>}
      {best && trades.data && (
        <>
          {open ? (
            <button type="button" onClick={open} className="text-left underline-offset-2 hover:underline">
              {said}
            </button>
          ) : (
            <span>{said}</span>
          )}
          <Badge variant="ok" appearance="pill" className="tabular-nums">
            {gain(best, trades.data.ranked_by, trades.data.measure)}
          </Badge>
        </>
      )}
      {trades.data && !best && (
        <span className="text-muted-foreground">No trades worth offering.</span>
      )}
      <Link
        to={href(competition.key, league.league_id, "trades")}
        className="font-mono text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground"
      >
        All trades
      </Link>
    </div>
  );
}

/**
 * What a trade gains you on the figure the list is ranked by, in words: '+21.4 pts rest of season',
 * '+1.25 cats rest of season', 'playoff odds +4.0 pts'.
 */
export function gain(
  idea: TradeIdea,
  ranked: Trades["ranked_by"],
  measure: Trades["measure"] = "points",
): string {
  if (ranked === "playoffs_change")
    return `playoff odds ${percentPoints(idea.playoffs_change)}`;

  if (measure === "categories")
    return `${signed(idea.total, 2)} cats rest of season`;

  return `${signed(idea.total)} pts rest of season`;
}
