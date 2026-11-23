import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type ActivityRow, type Competition, type League, type LeagueSchedule } from "@/lib/api";
import { keys } from "@/lib/queries";
import { ListCard } from "@/components/ui/list";
import { Empty, QueryState } from "@/components/ui/state";
import { LeagueHeader } from "@/components/league/page-header";
import { useDrawers } from "@/components/league/drawers";
import { MoveDrawer, MoveRow, backTo } from "@/components/league/move";

/**
 * What the league did lately, newest first; a row opens the move in full.
 *
 * The row says it in one line, which is all a scan needs. The move itself
 * names each player and whose roster took him. A player there opens his page.
 */
export function ActivityPanel({ competition, league }: { competition: Competition; league: League }) {
  const schedule = useQuery<LeagueSchedule, Error>({
    queryKey: keys.schedule(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).schedule,
  });
  const rows = schedule.data?.activity;
  return (
    <>
      <LeagueHeader league={league} />
      <QueryState query={schedule} lines={6} />
      {rows && rows.length === 0 && <Empty title="No activity" />}
      {rows && rows.length > 0 && (
        <div className="p-5">
          <Moves competition={competition} league={league} rows={rows} />
        </div>
      )}
    </>
  );
}

function Moves({ competition, league, rows }: { competition: Competition; league: League; rows: ActivityRow[] }) {
  const [open, setOpen] = useState<ActivityRow | null>(null);
  const { openPlayer, openComparison, drawer } = useDrawers(competition, league);
  return (
    <>
      <ListCard title="Recent activity" count={`${rows.length} moves`}>
        {rows.map((row, i) => (
          <MoveRow key={`${row.when}-${i}`} move={row} onOpen={setOpen} />
        ))}
      </ListCard>
      <MoveDrawer
        move={open}
        onClose={() => setOpen(null)}
        onOpenPlayer={(id) => {
          const from = open!;
          setOpen(null);
          openPlayer(id, backTo(from, () => setOpen(from)));
        }}
        onCompare={(ids) => {
          const from = open!;
          setOpen(null);
          openComparison({ ids }, backTo(from, () => setOpen(from)));
        }}
      />
      {drawer}
    </>
  );
}
