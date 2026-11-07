import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Search, Sparkles, X } from "lucide-react";
import { api, type League, type PlayerCall, type PlayerPage, type Competition } from "@/lib/api";
import { Card, CardHeader } from "@/components/ui/card";
import { IconButton } from "@/components/ui/icon-button";
import { RosterTable, toOrder } from "@/components/ui/roster-table";
import type { SortState } from "@/components/ui/data-table";
import { Busy, QueryState } from "@/components/ui/state";
import { ToggleChip } from "@/components/ui/toggle";
import { usePlayerDrawer } from "@/components/ui/player";
import { Input } from "@/components/ui/input";
import { Verdict } from "@/components/ui/verdict";
import { ErrorNote } from "@/components/ui/error-note";
import { LeagueHeader } from "@/components/ui/page-header";
import { keys, useCapabilities } from "@/lib/queries";
import type { Variant } from "@/lib/tone";

const CALL: Record<PlayerCall["decision"], { label: string; variant: Variant }> = {
  ADD: { label: "Add", variant: "ok" },
  WATCH: { label: "Watch", variant: "warn" },
  PASS: { label: "Pass", variant: "muted" },
};

/** The model's call on one player, under his row — said in words, not only color. */
function CallLine({ call }: { call: PlayerCall }) {
  const { label, variant } = CALL[call.decision];
  return (
    <Verdict
      label={call.drop ? `${label}, drop ${call.drop}` : label}
      variant={variant}
      reason={call.reason}
      stale={call.stale}
    />
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

  const leagueApi = api.league(competition.key, league.league_id);
  const page = useQuery<PlayerPage, Error>({
    queryKey: [...keys.freeAgents(competition.key, league.league_id), search, position, sort, offset],
    // No limit asked for: a page is the server's size, which it says on the page.
    queryFn: () => leagueApi.freeAgents({ offset, search, position, ...toOrder(sort) }),
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
  const capabilities = useCapabilities().data;
  const canJudge = (capabilities?.ai ?? false) && competition.judges_wire;
  // As many as the server judges at once: a screen's worth of the best.
  const judged = capabilities?.limits.judged ?? 0;
  // Kept calls on the rows on screen, read without asking the model: a call
  // outlives the page, and one whose player has moved on since comes back
  // marked stale rather than gone.
  const visible = page.data?.players.map((p) => p.player_id) ?? [];
  const callsKey = keys.freeAgentCalls(competition.key, league.league_id);
  const kept = useQuery<PlayerCall[], Error>({
    queryKey: [...callsKey, visible.join(",")],
    queryFn: () => leagueApi.freeAgentCalls(visible),
    enabled: canJudge && visible.length > 0,
  });
  const calls = Object.fromEntries((kept.data ?? []).map((c) => [c.player_id, c]));
  const queryClient = useQueryClient();
  const judge = useMutation<PlayerCall[], Error, string[]>({
    mutationFn: leagueApi.judgeFreeAgents,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: callsKey }),
  });

  const total = page.data?.total ?? 0;
  const size = page.data?.limit ?? 0;
  const shown = page.data?.players.length ?? 0;
  const filtered = Boolean(search || position);

  return (
    <>
      <LeagueHeader league={league} />

      <QueryState query={page} lines={6} />

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
                    label={`Judge the first ${Math.min(shown, judged)} shown`}
                    icon={<Sparkles />}
                    onClick={() => judge.mutate(page.data.players.slice(0, judged).map((p) => p.player_id))}
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
            {judge.isError && <ErrorNote error={judge.error} className="mx-4 my-3" />}

            <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
              <div className="relative min-w-0 flex-1">
                <Search
                  className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
                  aria-hidden
                />
                <Input
                  value={search}
                  onChange={(e) => reset(setSearch)(e.target.value)}
                  placeholder="Search by name, club or status"
                  aria-label="Search available players"
                  className="pl-8"
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

            {total > size && (
              <div className="flex items-center justify-between border-t border-border px-4 py-3">
                <span className="font-mono text-[11px] text-muted-foreground">
                  Page {Math.floor(offset / size) + 1} of {Math.ceil(total / size)}
                </span>
                <div className="flex items-center gap-1">
                  <IconButton
                    label="Previous page"
                    icon={<ChevronLeft />}
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - size))}
                  />
                  <IconButton
                    label="Next page"
                    icon={<ChevronRight />}
                    disabled={offset + size >= total}
                    onClick={() => setOffset(offset + size)}
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
