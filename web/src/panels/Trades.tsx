import { useQuery } from "@tanstack/react-query";
import { ArrowDown } from "lucide-react";
import { api, type Competition, type League, type TradeIdea, type Trades } from "@/lib/api";
import { ListCard } from "@/components/ui/list";
import { Table, Td, Th } from "@/components/ui/table";
import { Hint } from "@/components/ui/tooltip";
import { Meta } from "@/components/ui/label";
import { percent, percentPoints, signed } from "@/lib/format";
import { CardNote } from "@/components/ui/state";
import { keys } from "@/lib/queries";
import { LeagueHeader } from "@/components/ui/page-header";
import { cn } from "@/lib/utils";

/**
 * Half a point — of playoff chance, or of starters' points a week — below
 * which a change is noise and is not tinted either way.
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

type Figured = Trades["ranked_by"] | "points" | "playoff_points";

/** The figures for you, each a column, with what each measures on hover. */
const FIGURES: { key: Figured; label: string; about: string }[] = [
  { key: "points", label: "Season /wk", about: "Your starters' points a week, rest of the regular season" },
  { key: "playoff_points", label: "Playoffs /wk", about: "Your starters' points a playoff week" },
  {
    key: "total",
    label: "Total",
    about: "Your starters' points, rest of season: playoff weeks weighed by your odds",
  },
  { key: "playoffs_change", label: "Odds", about: "Your playoff chance, and where it ends up" },
];

/**
 * The trades that would do most for you, with who to offer each to and why he might say yes.
 *
 * A table, one trade a row, because the trades are compared with each other:
 * what each gives, gets, and does for you, read down a column. Ordered by the
 * server on the figure that matters most where you stand — your playoff chance
 * on the bubble, your points over the rest of the season once that is safe —
 * and that column says so. A trade can cost the regular season for the
 * playoffs; both columns show, so the cost is in view beside the gain.
 *
 * Fetched apart from the squad: each trade is a season played out thousands
 * of times, which is seconds the roster should not wait on.
 */
function TradeIdeas({ competition, league }: { competition: Competition; league: League }) {
  const trades = useQuery<Trades, Error>({
    queryKey: keys.trades(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).trades,
  });

  const ideas = trades.data?.ideas;
  const ranked = trades.data?.ranked_by;
  // Playoff weeks the platform has not projected yet have no column rather than one of dashes.
  const figures = FIGURES.filter((f) => f.key !== "playoff_points" || ideas?.some((i) => i.playoff_points != null));
  const pricing = priced(ideas ?? []);
  return (
    <ListCard
      title="Trades worth offering"
      count={ideas ? `${ideas.length} found` : undefined}
      loading={trades.isLoading}
      error={trades.error}
    >
      {ideas?.length === 0 && <CardNote>No trades worth offering.</CardNote>}
      {ideas && ideas.length > 0 && (
        <Table>
          <thead>
            <tr>
              <Th>Give</Th>
              <Th>Get</Th>
              <Th>Partner</Th>
              {figures.map((f) => (
                <Th key={f.key} className="text-right">
                  <Hint
                    label={f.key === ranked ? `${f.about}. Best first.` : f.about}
                    side="left"
                    className="inline-flex items-center gap-1"
                  >
                    {f.key === ranked && <ArrowDown className="size-3" aria-label="ordered by" />}
                    {f.label}
                  </Hint>
                </Th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ideas.map((idea) => (
              <tr key={`${idea.team_id}-${idea.giving.join()}-${idea.receiving.join()}`}>
                <Td>
                  <Players names={idea.giving} pricing={pricing} />
                </Td>
                <Td>
                  <Players names={idea.receiving} pricing={pricing} />
                  {idea.pickup && <Aside>+ add {idea.pickup}</Aside>}
                </Td>
                <Td>
                  <span className="block whitespace-nowrap">{idea.team}</span>
                  <Aside>{theirCase(idea)}</Aside>
                </Td>
                {figures.map((f) => (
                  <Td key={f.key} className={cn("whitespace-nowrap text-right", f.key === ranked && "font-medium")}>
                    <Figure idea={idea} figure={f.key} />
                  </Td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {trades.data?.pickup && <CardNote>Two-for-ones free a spot: add {trades.data.pickup}</CardNote>}
    </ListCard>
  );
}

/** A quiet second line in a cell. */
function Aside({ children }: { children: React.ReactNode }) {
  return <Meta className="block whitespace-nowrap">{children}</Meta>;
}

/** One side of a trade, a player a line, his pricing on hover where it is off his projection. */
function Players({ names, pricing }: { names: string[]; pricing: Map<string, string> }) {
  return (
    <>
      {names.map((name) => {
        const why = pricing.get(name);
        return (
          <span key={name} className="block whitespace-nowrap">
            {why ? (
              <Hint label={why} name={`${name}: ${why}`} dotted>
                {name}
              </Hint>
            ) : (
              name
            )}
          </span>
        );
      })}
    </>
  );
}

/** One figure for you; a change is tinted only where it is noticeable, and its sign says it in text too. */
function Figure({ idea, figure }: { idea: TradeIdea; figure: Figured }) {
  if (figure === "playoffs_change") {
    const change = idea.playoffs_change * 100;
    return (
      <>
        <span className={tint(change)}>{percentPoints(idea.playoffs_change)}</span>
        <Aside>to {percent(idea.playoffs)}</Aside>
      </>
    );
  }
  const value = figure === "points" ? idea.points : figure === "total" ? idea.total : idea.playoff_points;
  if (value == null) return <span className="text-muted-foreground">—</span>;
  return <span className={tint(value)}>{signed(value)}</span>;
}

function tint(change: number): string {
  return change >= NOTICEABLE ? "text-ok" : change <= -NOTICEABLE ? "text-warn" : "";
}

/**
 * Each player's pricing, by the name a trade lists him under, across the whole list.
 *
 * The server says it once, on the first trade he is in; a hover on any trade
 * he is in should still answer it.
 */
export function priced(ideas: TradeIdea[]): Map<string, string> {
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
 * and in it, his starters.
 */
export function theirCase(idea: TradeIdea): string {
  if (idea.their_playoffs < 0.05) return `out of the race, ${percent(idea.their_playoffs)}`;
  return `their starters ${signed(idea.their_points)} /wk`;
}
