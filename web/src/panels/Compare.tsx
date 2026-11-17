import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus, Search, X } from "lucide-react";
import { api, type Competition, type League, type PlayerComparison, type PlayerRef } from "@/lib/api";
import { keys } from "@/lib/queries";
import { MAX_COMPARED, useCompared } from "@/lib/compare";
import { Card, CardHeader } from "@/components/ui/card";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { ListRow } from "@/components/ui/list";
import { Empty, QueryState } from "@/components/ui/state";
import { Table, Td, Th } from "@/components/ui/table";
import { LeagueHeader } from "@/components/ui/page-header";
import { Chips, Portrait, usePlayerDrawer } from "@/components/ui/player";
import { cn } from "@/lib/utils";

/**
 * Up to four players side by side.
 *
 * Added from any player's drawer, from a move in the league's activity, or by
 * name here where the competition can find players by name.
 */
export function ComparePanel({ competition, league }: { competition: Competition; league: League }) {
  const { openPlayer, drawer } = usePlayerDrawer(competition, league);
  const compared = useCompared(competition.key, league.league_id);
  const leagueApi = api.league(competition.key, league.league_id);

  const comparison = useQuery<PlayerComparison, Error>({
    queryKey: keys.compare(competition.key, league.league_id, compared.ids),
    queryFn: () => leagueApi.compare(compared.ids),
    enabled: compared.ids.length > 0,
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <LeagueHeader league={league} />
      <div className="flex flex-col gap-4 p-5">
        {competition.searches_players && !compared.full && (
          <Finder competition={competition} league={league} onPick={compared.add} exclude={compared.ids} />
        )}
        {compared.ids.length === 0 ? (
          <Empty
            title="Nobody to compare"
            detail={`Add up to ${MAX_COMPARED} players${competition.searches_players ? " above, or" : ""} from any player's page.`}
          />
        ) : (
          <>
            <QueryState query={comparison} lines={6} />
            {comparison.data && (
              <Grid comparison={comparison.data} onOpen={openPlayer} onRemove={compared.remove} />
            )}
          </>
        )}
      </div>
      {drawer}
    </>
  );
}

function Grid({
  comparison,
  onOpen,
  onRemove,
}: {
  comparison: PlayerComparison;
  onOpen: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  const { players, table } = comparison;
  return (
    <Card>
      <CardHeader>
        <span>Compare</span>
        <span>
          {players.length} of {MAX_COMPARED}
        </span>
      </CardHeader>
      <Table>
        <thead>
          <tr>
            <Th />
            {players.map((p) => (
              <Th key={p.player_id} className="min-w-40 normal-case tracking-normal">
                <div className="flex items-start justify-between gap-2">
                  <Portrait src={p.image_url} className="size-14" />
                  <button type="button" onClick={() => onOpen(p.player_id)} className="min-w-0 flex-1 text-left">
                    <div className="truncate font-sans text-[13.5px] font-semibold text-foreground">{p.name}</div>
                    <div className="font-mono text-[11px] text-muted-foreground">
                      {[p.position, p.team].filter(Boolean).join(" · ")}
                    </div>
                    {p.headline && (
                      <div className="mt-1 font-mono text-[15px] font-semibold text-foreground tabular-nums">
                        {p.headline}
                      </div>
                    )}
                  </button>
                  <IconButton label={`Remove ${p.name}`} icon={<X />} onClick={() => onRemove(p.player_id)} />
                </div>
                <Chips detail={p} className="mt-1" />
              </Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row) => (
            <tr key={row.label}>
              <Td className="whitespace-nowrap text-muted-foreground">{row.label}</Td>
              {row.values.map((value, i) => (
                <Td
                  key={`${row.label}-${i}`}
                  className={cn("font-mono text-[12.5px]", value === table.absent && "text-muted-foreground/50")}
                >
                  {value}
                </Td>
              ))}
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

/** Find a player by name and add him; the ones already compared are not offered again. */
function Finder({
  competition,
  league,
  onPick,
  exclude,
}: {
  competition: Competition;
  league: League;
  onPick: (id: string) => void;
  exclude: string[];
}) {
  const [search, setSearch] = useState("");
  const found = useQuery<PlayerRef[], Error>({
    queryKey: keys.playerSearch(competition.key, league.league_id, search.trim()),
    queryFn: () => api.league(competition.key, league.league_id).searchPlayers(search.trim()),
    enabled: search.trim().length >= 2,
  });
  const offered = (found.data ?? []).filter((p) => !exclude.includes(p.player_id));
  return (
    <Card>
      <div className="relative px-4 py-3">
        <Search
          className="pointer-events-none absolute left-6.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Add a player"
          aria-label="Find a player to compare"
          className="pl-8"
        />
      </div>
      {offered.map((p) => (
        <ListRow
          key={p.player_id}
          onClick={() => {
            onPick(p.player_id);
            setSearch("");
          }}
        >
          <Plus className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <span className="min-w-0 flex-1 truncate">{p.name}</span>
          <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{p.detail}</span>
        </ListRow>
      ))}
    </Card>
  );
}
