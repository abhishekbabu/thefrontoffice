import { useQuery } from "@tanstack/react-query";
import { api, type Competition, type League, type TradeIdea, type Trades } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ListCard, ListRow } from "@/components/ui/list";
import { percent, percentPoints, signed } from "@/lib/format";
import { CardNote } from "@/components/ui/state";
import { keys } from "@/lib/queries";
import { LeagueHeader } from "@/components/ui/page-header";

/**
 * Half a point — of playoff chance, or of starters' points a week — below
 * which a change is noise ("+0.0 pts, to 99%") and goes unsaid.
 */
export const NOTICEABLE = 0.5;

/** The trades worth offering. The deadline is the Matchup to-do's and the Schedule's to say. */
export function TradesPanel({ competition, league }: { competition: Competition; league: League }) {
  return (
    <>
      <LeagueHeader league={league} />
      <div className="flex flex-col gap-4 p-5">
        <TradeIdeas competition={competition} league={league} />
      </div>
    </>
  );
}

/**
 * The trades that would do most for you, with who to offer each to and why he might say yes.
 *
 * Beside the weeks ahead because a trade is a roster move like a pickup, and
 * often the fix for a short week no free agent closes. Fetched apart from the
 * squad: each one is a season played out thousands of times, which is seconds
 * the roster should not wait on.
 *
 * Two figures for you, because a trade does two things: what it does to your
 * playoff chance, and what it does to your lineup once you are there. The
 * badge is the second where the playoff weeks are projected, since a team that
 * is in needs December more than another point of chance.
 *
 * Under each, the players whose own games price them off their projection,
 * and why: a trade resting on a role that just changed should say so. The
 * server says each once, and a pickup most trades share once, under the list.
 */
function TradeIdeas({ competition, league }: { competition: Competition; league: League }) {
  const trades = useQuery<Trades, Error>({
    queryKey: keys.trades(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).trades,
  });

  const ideas = trades.data?.ideas;
  return (
    <ListCard
      title="Trades worth offering"
      count={ideas ? `${ideas.length} found` : undefined}
      loading={trades.isLoading}
      error={trades.error}
    >
      {ideas?.length === 0 && (
        <CardNote>No trades worth offering.</CardNote>
      )}
      {ideas?.map((idea) => (
        <ListRow key={`${idea.team_id}-${idea.giving.join()}-${idea.receiving.join()}`}>
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="truncate">
              Give {idea.giving.join(" and ")} for {idea.receiving.join(", ")}
            </span>
            <span className="truncate font-mono text-[11px] text-muted-foreground">
              {[`with ${idea.team} (${theirCase(idea)})`, ...changes(idea)].join(" · ")}
            </span>
            {idea.pickup && (
              <span className="truncate font-mono text-[11px] text-muted-foreground">
                frees a spot: add {idea.pickup}
              </span>
            )}
            {/* Why a price is not the projection: wrapped, since the reason is the point. */}
            {idea.form.map((line) => (
              <span key={line.label} className="text-[11px] leading-snug text-muted-foreground">
                <span className="text-foreground/80">{line.label}</span> {line.value}
              </span>
            ))}
          </span>
          {/* The figure that matters most, said in words as well as tinted. */}
          <Badge variant="ok" appearance="pill" className="shrink-0 tabular-nums">
            {idea.playoff_points != null
              ? `${signed(idea.playoff_points)} a playoff week`
              : `${signed(idea.points)} a week`}
          </Badge>
        </ListRow>
      ))}
      {trades.data?.pickup && <CardNote>Two-for-ones free a spot: add {trades.data.pickup}</CardNote>}
    </ListCard>
  );
}

/**
 * Why the other manager might say yes: out of the race he weighs only worth,
 * and in it, his starters.
 */
export function theirCase(idea: TradeIdea): string {
  if (idea.their_playoffs < 0.05) return `out of the race, ${percent(idea.their_playoffs)}`;
  return `their starters ${signed(idea.their_points)} a week`;
}

/**
 * What a trade does to your playoff chance, and to the regular season where
 * the badge is the playoffs' — each only where it moves by a noticeable amount.
 */
export function changes(idea: TradeIdea): string[] {
  const said: string[] = [];
  if (Math.abs(idea.playoffs_change * 100) >= NOTICEABLE) {
    said.push(`your playoffs ${percentPoints(idea.playoffs_change)}, to ${percent(idea.playoffs)}`);
  }
  if (idea.playoff_points != null && Math.abs(idea.points) >= NOTICEABLE) {
    said.push(`rest of season ${signed(idea.points)} a week`);
  }
  return said;
}
