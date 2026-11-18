import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type Competition, type League, type LeagueSchedule } from "@/lib/api";
import { keys } from "@/lib/queries";
import { href } from "@/lib/route";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/table";
import { clickable } from "@/lib/clickable";
import { Empty, QueryState } from "@/components/ui/state";
import { cn } from "@/lib/utils";
import { LeagueHeader } from "@/components/ui/page-header";

/**
 * The league table: record, points for and against, FAAB left and waiver
 * order. A row opens that team's roster.
 */
export function LeaguePanel({ competition, league }: { competition: Competition; league: League }) {
  const schedule = useQuery<LeagueSchedule, Error>({
    queryKey: keys.schedule(competition.key, league.league_id),
    queryFn: api.league(competition.key, league.league_id).schedule,
  });
  const navigate = useNavigate();
  const rosters = href(competition.key, league.league_id, "rosters");

  return (
    <>
      <LeagueHeader league={league} />
      <QueryState query={schedule} lines={6} />
      {schedule.data && schedule.data.standings.length === 0 && <Empty title="No table" />}
      {schedule.data && schedule.data.standings.length > 0 && (
        <div className="p-5">
          <Standings rows={schedule.data.standings} onOpen={(id) => navigate(`${rosters}?team=${encodeURIComponent(id)}`)} />
        </div>
      )}
    </>
  );
}

function Standings({
  rows,
  onOpen,
}: {
  rows: LeagueSchedule["standings"];
  onOpen: (teamId: string) => void;
}) {
  // Only the columns this league fills: FPL has no waiver budget, and a league
  // that is not simulated has no playoff chance.
  const has = (key: "record" | "points_against" | "waiver_budget" | "waiver_order" | "playoffs") =>
    rows.some((row) => row[key]);
  return (
    <Card>
      <CardHeader>
        <span>Table</span>
        <span>{rows.length} teams</span>
      </CardHeader>
      <Table>
        <thead>
          <tr>
            <Th className="w-8 text-right">#</Th>
            <Th>Team</Th>
            {has("record") && <Th className="text-right">Record</Th>}
            <Th className="text-right">{has("points_against") ? "PF" : "Pts"}</Th>
            {has("points_against") && <Th className="text-right">PA</Th>}
            {has("waiver_budget") && <Th className="text-right">FAAB</Th>}
            {has("waiver_order") && <Th className="text-right">Waiver</Th>}
            {has("playoffs") && <Th className="text-right">Playoffs</Th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={`${row.rank}-${row.name}`}
              {...clickable(row.team_id ? () => onOpen(row.team_id) : undefined)}
              className={cn(row.team_id && "cursor-pointer hover:bg-muted", row.is_mine && "bg-muted/60")}
            >
              <Td className="text-right font-mono text-muted-foreground">{row.rank}</Td>
              <Td>
                <span className="flex min-w-0 items-center gap-2">
                  <span className="truncate">{row.name}</span>
                  {row.is_mine && (
                    <Badge variant="muted" appearance="label" className="shrink-0">
                      you
                    </Badge>
                  )}
                  {row.detail && (
                    <span className="hidden truncate font-mono text-[11px] text-muted-foreground sm:block">
                      {row.detail}
                    </span>
                  )}
                </span>
              </Td>
              {has("record") && <Td className="text-right font-mono">{row.record}</Td>}
              <Td className="text-right font-mono">{row.points}</Td>
              {has("points_against") && <Td className="text-right font-mono">{row.points_against}</Td>}
              {has("waiver_budget") && <Td className="text-right font-mono">{row.waiver_budget}</Td>}
              {has("waiver_order") && <Td className="text-right font-mono">{row.waiver_order}</Td>}
              {has("playoffs") && <Td className="text-right font-mono text-muted-foreground">{row.playoffs}</Td>}
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}
