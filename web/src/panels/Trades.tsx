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
import { LeagueHeader } from "@/components/league/page-header";
import { cn } from "@/lib/utils";
import { clickable } from "@/lib/clickable";
import { useDrawers } from "@/components/league/drawers";
import { traded, type Comparing } from "@/components/league/compare";

/**
 * Half a point — of playoff chance, or of starters' points a week — below
 * which a change is noise and is not tinted either way.
 */
export const NOTICEABLE = 0.5;

/** The same for a figure counted in categories: a tenth of one a week. */
export const NOTICEABLE_CATEGORIES = 0.1;

type Measure = Trades["measure"];

/** The trades worth offering, and the day trading closes where the league's settings name one. */
export function TradesPanel({ competition, league }: { competition: Competition; league: League }) {
  const { openComparison, drawer } = useDrawers(competition, league);
  return (
    <>
      <LeagueHeader league={league} />
      <div className="flex flex-col gap-4 p-5">
        <TradeIdeas competition={competition} league={league} onCompare={openComparison} />
      </div>
      {drawer}
    </>
  );
}

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
function TradeIdeas({
  competition,
  league,
  onCompare,
}: {
  competition: Competition;
  league: League;
  /** A row opens both sides of its trade side by side. */
  onCompare: (comparing: Comparing) => void;
}) {
  const trades = useQuery<Trades, Error>({
    queryKey: keys.trades(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).trades,
  });

  const ideas = trades.data?.ideas;
  const ranked = trades.data?.ranked_by;
  const measure = trades.data?.measure ?? "points";
  // Playoff weeks the platform has not projected yet have no column rather than one of dashes.
  const figures = FIGURES[measure].filter(
    (f) => f.key !== "playoff_points" || ideas?.some((i) => i.playoff_points != null),
  );
  const pricing = priced(ideas ?? []);
  const closes = trades.data?.deadline ? ` · deadline ${day(trades.data.deadline)}` : "";
  return (
    <ListCard
      title="Trades worth offering"
      count={ideas ? `${ideas.length} found${closes}` : undefined}
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
              <tr
                key={`${idea.team_id}-${idea.giving.join()}-${idea.receiving.join()}`}
                {...clickable(traded(idea, onCompare))}
                className={cn(idea.giving_ids.length + idea.receiving_ids.length > 1 && "cursor-pointer hover:bg-muted")}
              >
                <Td>
                  <Players names={idea.giving} pricing={pricing} />
                </Td>
                <Td>
                  <Players names={idea.receiving} pricing={pricing} />
                  {idea.pickup && <Aside>+ add {idea.pickup}</Aside>}
                </Td>
                <Td>
                  <span className="block whitespace-nowrap">{idea.team}</span>
                  <Aside>{theirCase(idea, measure)}</Aside>
                </Td>
                {figures.map((f) => (
                  <Td key={f.key} className={cn("whitespace-nowrap text-right", f.key === ranked && "font-medium")}>
                    <Figure idea={idea} figure={f.key} measure={measure} />
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
function Figure({ idea, figure, measure }: { idea: TradeIdea; figure: Figured; measure: Measure }) {
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
  const categories = measure === "categories";
  return (
    <span className={tint(value, categories ? NOTICEABLE_CATEGORIES : NOTICEABLE)}>
      {signed(value, categories ? 2 : 1)}
    </span>
  );
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
 * and in it, his starters — or in a category league, the categories he
 * expects to take, which every trade offered there raises.
 */
export function theirCase(idea: TradeIdea, measure: Measure = "points"): string {
  if (measure === "categories") return `their cats ${signed(idea.their_points, 2)} /wk`;
  if (idea.their_playoffs < 0.05) return `out of the race, ${percent(idea.their_playoffs)}`;
  return `their starters ${signed(idea.their_points)} /wk`;
}
