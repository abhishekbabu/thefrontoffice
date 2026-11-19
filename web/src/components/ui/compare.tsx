import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useKept } from "@/lib/useKept";
import { useNavigate } from "react-router-dom";
import { Maximize2, Star, X } from "lucide-react";
import { api, type PlayerComparison, type TradeIdea } from "@/lib/api";
import { keys } from "@/lib/queries";
import { MAX_COMPARED, useCompared } from "@/lib/compare";
import { href } from "@/lib/route";
import { Card } from "@/components/ui/card";
import { SlideOver, SlideOverHeader, type Back } from "@/components/ui/dialog";
import { IconButton } from "@/components/ui/icon-button";
import { LABEL, Meta } from "@/components/ui/label";
import { QueryState } from "@/components/ui/state";
import { Table, Td, Th } from "@/components/ui/table";
import { Chips, Portrait } from "@/components/ui/player";
import { cn } from "@/lib/utils";

/**
 * What a comparison is opened with: whom, and how to head it.
 *
 * `tags` names each player's side where the comparison came from a decision —
 * "In" and "Out" on a to-do, "Give" and "Get" on a trade — so a column says
 * which way he goes before it says anything else.
 */
export type Comparing = { ids: string[]; title?: string; tags?: Record<string, string> };

/** What a trade opens, wherever it is listed: both sides of it, what you give then what you get, each column saying which. */
export function traded(idea: TradeIdea, onCompare: (comparing: Comparing) => void): (() => void) | undefined {
  const ids = [...idea.giving_ids, ...idea.receiving_ids];
  if (ids.length < 2) return undefined;
  const tags = {
    ...Object.fromEntries(idea.giving_ids.map((id) => [id, "Give"])),
    ...Object.fromEntries(idea.receiving_ids.map((id) => [id, "Get"])),
  };
  return () => onCompare({ ids, title: `Trade with ${idea.team}`, tags });
}

/** Players side by side, the same query wherever they are compared from. */
export function useComparison(competition: string, league: string, ids: string[]) {
  return useQuery<PlayerComparison, Error>({
    queryKey: keys.compare(competition, league, ids),
    queryFn: () => api.league(competition, league).compare(ids),
    enabled: ids.length > 0,
    placeholderData: keepPreviousData,
  });
}

/**
 * The comparison itself: a column per player and a row per measure, one
 * section per heading, the best of each row marked.
 *
 * Every competition's comparison is built by the server from what each
 * player's drawer shows, so this reads the same for a quarterback, a centre
 * and a goalkeeper; the Compare page and the drawer both draw it.
 */
export function ComparisonGrid({
  comparison,
  tags,
  onOpen,
  onRemove,
}: {
  comparison: PlayerComparison;
  tags?: Record<string, string>;
  onOpen: (id: string) => void;
  /** Where the list can be changed: the Compare page, not a decision's drawer. */
  onRemove?: (id: string) => void;
}) {
  const { players, tables } = comparison;
  return (
    <Table>
      <thead>
        <tr>
          <Th />
          {players.map((p) => (
            <Th key={p.player_id} className="min-w-40 normal-case tracking-normal">
              <div className="flex items-start justify-between gap-2">
                <Portrait src={p.image_url} className="size-14" />
                <button type="button" onClick={() => onOpen(p.player_id)} className="min-w-0 flex-1 text-left">
                  {tags?.[p.player_id] && <span className={cn(LABEL, "block")}>{tags[p.player_id]}</span>}
                  <div className="truncate font-sans text-[13.5px] font-semibold text-foreground">{p.name}</div>
                  <Meta as="div" className="font-normal">
                    {[p.position, p.team].filter(Boolean).join(" · ")}
                  </Meta>
                  {p.headline && (
                    <div className="mt-1 font-mono text-[15px] font-semibold text-foreground tabular-nums">
                      {p.headline}
                    </div>
                  )}
                </button>
                {onRemove && (
                  <IconButton label={`Remove ${p.name}`} icon={<X />} onClick={() => onRemove(p.player_id)} />
                )}
              </div>
              <Chips detail={p} className="mt-1" />
            </Th>
          ))}
        </tr>
      </thead>
      {tables.map((table) => (
        <tbody key={table.title}>
          {/* The heading once, over its rows, rather than as a prefix on every label. */}
          <tr>
            <th
              scope="colgroup"
              colSpan={players.length + 1}
              className={cn(LABEL, "border-b border-border bg-muted px-4 py-1.5 text-left")}
            >
              {table.title}
            </th>
          </tr>
          {table.rows.map((row) => (
            <tr key={row.label}>
              {/* Wraps rather than widening its column: a label naming who is out
                  ("Without Jalen Williams (O, back ~2 Mar), …") would push
                  the players off the side of a drawer. */}
              <Td className="w-[30%] min-w-28 text-muted-foreground">{row.label}</Td>
              {row.values.map((value, i) => (
                <Cell key={`${row.label}-${i}`} value={value} absent={value === table.absent} best={row.best.includes(i)} />
              ))}
            </tr>
          ))}
        </tbody>
      ))}
    </Table>
  );
}

/** One figure; the best of its row is set heavier, in the good color, and starred, so it reads without color too. */
function Cell({ value, absent, best }: { value: string; absent: boolean; best: boolean }) {
  return (
    <Td className={cn("font-mono text-[12.5px]", absent && "text-muted-foreground/50", best && "font-semibold text-ok")}>
      <span className="inline-flex items-center gap-1">
        {value}
        {best && (
          <>
            <Star className="size-3 fill-current" aria-hidden />
            <span className="sr-only">best</span>
          </>
        )}
      </span>
    </Td>
  );
}

/** "A vs B", or "A, B vs C" past two: who a comparison is of, for its title and a Back link to it. */
export function compareLabel(comparison: PlayerComparison | undefined, fallback = "Compare"): string {
  const names = comparison?.players.map((p) => p.name) ?? [];
  return names.length ? names.join(" vs ") : fallback;
}

/**
 * Who is on which side, where the comparison has sides: "Give Flournoy, Tyson · Get Likely".
 * A trade's players are not each against each, which "A vs B vs C" says they are.
 */
export function sides(comparison: PlayerComparison | undefined, tags: Record<string, string> | undefined): string {
  if (!comparison || !tags) return "";
  const by = new Map<string, string[]>();
  for (const player of comparison.players) {
    const tag = tags[player.player_id];
    if (tag) by.set(tag, [...(by.get(tag) ?? []), player.name]);
  }
  return [...by].map(([tag, names]) => `${tag} ${names.join(", ")}`).join(" · ");
}

/**
 * A comparison in a drawer, over whatever it was opened from: the players a
 * to-do weighs, a trade's two sides, a move's players. The Compare page is
 * the same grid kept across visits; this one is about the decision in front
 * of you, and can be carried over to that page.
 *
 * `comparing` of null is the closed state.
 */
export function ComparisonDrawer({
  competition,
  league,
  comparing,
  back,
  onClose,
  onOpenPlayer,
}: {
  competition: string;
  league: string;
  comparing: Comparing | null;
  back?: Back;
  onClose: () => void;
  /** Swap to one of the players; `label` names this comparison for his Back link. */
  onOpenPlayer: (id: string, label: string) => void;
}) {
  // Held so the drawer still has someone to show while it slides out.
  const shown = useKept(comparing) ?? { ids: [] };
  const ids = shown.ids.slice(0, MAX_COMPARED);

  const comparison = useComparison(competition, league, ids);
  const compared = useCompared(competition, league);
  const navigate = useNavigate();
  const names = compareLabel(comparison.data, "Players");
  return (
    <SlideOver
      open={comparing !== null}
      onClose={onClose}
      label={`Compare ${names}`}
      // A column per player: two read in the player drawer's width, three or four need more.
      className={cn("border-l border-border", ids.length > 2 ? "max-w-4xl" : "max-w-2xl")}
    >
      <SlideOverHeader
        title={shown.title ?? names}
        meta={shown.title ? sides(comparison.data, shown.tags) || names : `${ids.length} players`}
        back={back}
        onClose={onClose}
      >
        <IconButton
          label="Open on the Compare page"
          icon={<Maximize2 />}
          onClick={() => {
            compared.set(ids);
            onClose();
            void navigate(href(competition, league, "compare"));
          }}
        />
      </SlideOverHeader>
      <div className="flex flex-col gap-4 p-5">
        <QueryState query={comparison} lines={6} />
        {comparison.data && (
          <Card className="overflow-x-auto">
            <ComparisonGrid
              comparison={comparison.data}
              tags={shown.tags}
              onOpen={(id) => onOpenPlayer(id, `Compare · ${names}`)}
            />
          </Card>
        )}
      </div>
    </SlideOver>
  );
}
