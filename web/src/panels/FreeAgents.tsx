import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Search, Sparkles, X } from "lucide-react";
import { api, type League, type PlayerCall, type PlayerPage, type Competition } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { IconButton } from "@/components/ui/icon-button";
import { RosterTable } from "@/components/ui/roster-table";
import type { SortState } from "@/components/ui/data-table";
import { Busy, Loading } from "@/components/ui/state";
import { ToggleChip } from "@/components/ui/toggle";
import { usePlayerDrawer } from "@/components/ui/player";
import { cn } from "@/lib/utils";
import { ErrorNote } from "@/components/ui/error-note";
import { LeagueHeader } from "@/components/ui/page-header";

const PAGE = 50;
/** As many as the server will judge at once: a screen's worth of the best. */
const JUDGE = 10;

const CALL: Record<PlayerCall["decision"], { label: string; variant: "ok" | "warn" | "muted" }> = {
  ADD: { label: "Add", variant: "ok" },
  WATCH: { label: "Watch", variant: "warn" },
  PASS: { label: "Pass", variant: "muted" },
};

/**
 * The model's call on one player, under his row — said in words, not only
 * color. A stale one stays, faded and labelled: the reasoning may still hold,
 * but it was about a situation that has since changed.
 */
function CallLine({ call }: { call: PlayerCall }) {
  const { label, variant } = CALL[call.decision];
  return (
    <div className={cn("flex items-baseline gap-2 whitespace-normal text-[12.5px]", call.stale && "opacity-60")}>
      <Badge variant={call.stale ? "muted" : variant} appearance="status" className="shrink-0">
        {call.drop ? `${label}, drop ${call.drop}` : label}
      </Badge>
      <span className="text-muted-foreground">{call.reason}</span>
      {call.stale && (
        <span className="ml-auto shrink-0 font-mono text-[10.5px] uppercase tracking-[0.06em] text-muted-foreground">
          stale — re-judge
        </span>
      )}
    </div>
  );
}

/**
 * Who is still out there.
 *
 * The other half of a roster: what you hold is only half the question, and the
 * half that changes is the wire. Football's pool is four thousand players, so
 * this is a window onto a ranking rather than the ranking itself — which is
 * why the sort, the filters and the paging all happen on the server. Sorting
 * the fifty rows in hand would answer a different question than the one the
 * column header appears to ask.
 */
export function FreeAgentsPanel({ competition, league }: { competition: Competition; league: League }) {
  const { openPlayer, drawer } = usePlayerDrawer(competition, league);
  const [search, setSearch] = useState("");
  const [position, setPosition] = useState("");
  const [sort, setSort] = useState<SortState | null>(null);
  const [offset, setOffset] = useState(0);

  const page = useQuery<PlayerPage, Error>({
    queryKey: ["free-agents", competition.key, league.league_id, search, position, sort, offset],
    queryFn: () =>
      api.freeAgents(competition.key, league.league_id, {
        offset,
        limit: PAGE,
        search,
        position,
        sort: sort?.column ?? "",
        descending: sort?.descending ?? true,
      }),
    // Keeps the table on screen while the next page loads, so paging does not
    // blink the page out and back.
    placeholderData: keepPreviousData,
  });

  /** Any change to what is being asked for starts again at the first page. */
  const reset = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    setOffset(0);
  };

  // The model's calls, kept across paging and filtering: a call on a player
  // is still his when he scrolls off the page and back.
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities });
  const canJudge = (capabilities.data?.ai ?? false) && competition.judges_wire;
  // Kept calls on the rows on screen, read without asking the model: a call
  // outlives the page, and one whose player has moved on since comes back
  // marked stale rather than gone.
  const visible = page.data?.players.map((p) => p.player_id) ?? [];
  const callsKey = ["free-agent-calls", competition.key, league.league_id, visible.join(",")];
  const kept = useQuery<PlayerCall[], Error>({
    queryKey: callsKey,
    queryFn: () => api.freeAgentCalls(competition.key, league.league_id, visible),
    enabled: canJudge && visible.length > 0,
  });
  const calls = Object.fromEntries((kept.data ?? []).map((c) => [c.player_id, c]));
  const queryClient = useQueryClient();
  const judge = useMutation<PlayerCall[], Error, string[]>({
    mutationFn: (ids) => api.judgeFreeAgents(competition.key, league.league_id, ids),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["free-agent-calls", competition.key, league.league_id] }),
  });

  const total = page.data?.total ?? 0;
  const shown = page.data?.players.length ?? 0;
  const filtered = Boolean(search || position);

  return (
    <>
      <LeagueHeader league={league} />

      {page.isError && <ErrorNote error={page.error} />}
      {page.isLoading && <Loading lines={6} />}

      {page.data && (
        <div className="flex flex-col gap-4 p-5">
          <Card>
            <CardHeader>
              <span>Available</span>
              <span className="flex items-center gap-2">
                {judge.isPending && <Busy>judging…</Busy>}
                {/* The first rows on screen: the sort has already put the ones
                    worth a call first, whichever sort that is. */}
                {canJudge && shown > 0 && (
                  <IconButton
                    label={`Judge the first ${Math.min(shown, JUDGE)} shown`}
                    icon={<Sparkles />}
                    onClick={() => judge.mutate(page.data.players.slice(0, JUDGE).map((p) => p.player_id))}
                    disabled={judge.isPending}
                  />
                )}
                <span>
                  {total === 0
                    ? "none"
                    : `${offset + 1}-${offset + shown} of ${total.toLocaleString()}`}
                </span>
              </span>
            </CardHeader>
            {judge.isError && <ErrorNote error={judge.error} />}

            <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
              <div className="relative min-w-0 flex-1">
                <Search
                  className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
                  aria-hidden
                />
                <input
                  value={search}
                  onChange={(e) => reset(setSearch)(e.target.value)}
                  placeholder="Search by name, club or status"
                  aria-label="Search available players"
                  className="h-9 w-full rounded-md border border-border bg-background pl-8 pr-2 text-[13px] outline-none placeholder:text-muted-foreground focus-visible:border-ring"
                />
              </div>
              {/* Read off the pool rather than written down: the positions
                  differ per competition, and a list here would be a fourth place to
                  edit. Off the unfiltered pool, so choosing one does not
                  remove the others. */}
              {page.data.positions.map((p) => (
                <ToggleChip
                  key={p}
                  pressed={position === p}
                  onClick={() => reset(setPosition)(position === p ? "" : p)}
                  className="font-mono text-[11px] uppercase tracking-[0.06em]"
                >
                  {p}
                </ToggleChip>
              ))}
              {filtered && (
                <IconButton
                  label="Clear filters"
                  icon={<X />}
                  onClick={() => {
                    setSearch("");
                    setPosition("");
                    setOffset(0);
                  }}
                />
              )}
            </div>

            <RosterTable
              players={page.data.players}
              empty={{
                title: filtered ? "Nothing matches" : "Nobody available",
                detail: filtered
                  ? "Try a different position, or clear the search."
                  : "Every player in this league is on a roster.",
              }}
              sort={sort}
              onSort={reset(setSort)}
              onOpen={openPlayer}
              detail={(player) => {
                const call = calls[player.player_id];
                return call && <CallLine call={call} />;
              }}
            />

            {total > PAGE && (
              <div className="flex items-center justify-between border-t border-border px-4 py-3">
                <span className="font-mono text-[11px] text-muted-foreground">
                  Page {Math.floor(offset / PAGE) + 1} of {Math.ceil(total / PAGE)}
                </span>
                <div className="flex items-center gap-1">
                  <IconButton
                    label="Previous page"
                    icon={<ChevronLeft />}
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - PAGE))}
                  />
                  <IconButton
                    label="Next page"
                    icon={<ChevronRight />}
                    disabled={offset + PAGE >= total}
                    onClick={() => setOffset(offset + PAGE)}
                  />
                </div>
              </div>
            )}
          </Card>
        </div>
      )}
      {drawer}
    </>
  );
}
