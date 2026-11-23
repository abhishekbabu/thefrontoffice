import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { api, type CaptureStatus, type Competition, type League, type PlayerComparison, type PlayerRef } from "@/lib/api";
import { keys } from "@/lib/queries";
import { MAX_COMPARED, useCompared } from "@/lib/compare";
import { Card, CardHeader } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/input";
import { Meta } from "@/components/ui/label";
import { ListRow } from "@/components/ui/list";
import { Empty, QueryState } from "@/components/ui/state";
import { LeagueHeader } from "@/components/league/page-header";
import { useDrawers } from "@/components/league/drawers";
import { ComparisonGrid, useComparison } from "@/components/league/compare";

/**
 * Up to four players side by side.
 *
 * Added from any player's drawer, from a move in the league's activity, or by
 * name here where the competition can find players by name.
 */
export function ComparePanel({ competition, league }: { competition: Competition; league: League }) {
  const { openPlayer, drawer } = useDrawers(competition, league);
  const compared = useCompared(competition.key, league.league_id);

  const comparison = useComparison(competition.key, league.league_id, compared.ids);

  return (
    <>
      <LeagueHeader competition={competition} league={league} />
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

/** The grid in a card, a column a player, each removable from the list. */
function Grid({
  comparison,
  onOpen,
  onRemove,
}: {
  comparison: PlayerComparison;
  onOpen: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <Card className="overflow-x-auto">
      <CardHeader>
        <span>Compare</span>
        <span>
          {comparison.players.length} of {MAX_COMPARED}
        </span>
      </CardHeader>
      <ComparisonGrid comparison={comparison} onOpen={onOpen} onRemove={onRemove} />
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
  // Read from a browser sync, only the players it carried can be found: say so once a search is under way.
  const sync = useQuery<CaptureStatus, Error>({
    queryKey: keys.capture(competition.platform),
    queryFn: () => api.captureStatus(competition.platform),
    enabled: competition.syncs,
  });
  const offered = (found.data ?? []).filter((p) => !exclude.includes(p.player_id));
  return (
    <Card>
      <div className="px-4 py-3">
        <SearchInput
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Add a player"
          aria-label="Find a player to compare"
        />
      </div>
      {sync.data?.active && search.trim().length >= 2 && (
        <Meta as="p" className="px-4 pb-2">
          Synced players only: rosters and the top of the wire.
        </Meta>
      )}
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
          <Meta className="shrink-0">{p.detail}</Meta>
        </ListRow>
      ))}
    </Card>
  );
}
