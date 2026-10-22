import { useQuery } from "@tanstack/react-query";
import { api, type Action, type League, type Competition, type Summary, type Urgency } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Loading } from "@/components/ui/state";
import { StatStrip } from "@/components/ui/stat";
import { LineupCard, SideCard } from "@/components/ui/lineup";
import { usePlayerDrawer } from "@/components/ui/player";
import { cn } from "@/lib/utils";
import { ErrorNote } from "@/components/ui/error-note";
import { LeagueHeader } from "@/components/ui/page-header";

/**
 * The week: where you stand, what you are fielding, and who against.
 *
 * No analysis here. Everything is read or computed from league state, so the
 * page is complete the moment it opens — and the report, which lives on its own
 * view, is then an argument about what is already on screen rather than the
 * only thing on it.
 */
export function ScoutPanel({ competition, league }: { competition: Competition; league: League }) {
  const { openPlayer, drawer } = usePlayerDrawer(competition, league);

  const week = useQuery<Summary, Error>({
    queryKey: ["summary", competition.key, league.league_id],
    queryFn: () => api.summary(competition.key, league.league_id),
  });

  return (
    <>
      {/* The week is what this page is about, so it belongs in the header
          rather than a row down among the figures. */}
      <LeagueHeader league={league} meta={[week.data?.window, league.detail].filter(Boolean).join(" · ")} />
      <StatStrip stats={week.data?.headline ?? []} />

      {week.isLoading && <Loading lines={4} />}
      {week.isError && <ErrorNote error={week.error} />}

      {week.data && (
        <div className="flex flex-col gap-4 p-5">
          {week.data.actions && <ActionList actions={week.data.actions} onOpen={openPlayer} />}

          {week.data.opponent ? (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <SideCard side={week.data.mine} label="You" onOpen={openPlayer} />
              <SideCard side={week.data.opponent} label="Opponent" onOpen={openPlayer} />
            </div>
          ) : (
            <LineupCard
              title="Your lineup"
              lineup={week.data.mine?.lineup ?? []}
              bench={week.data.mine?.bench ?? []}
              swaps={week.data.actions ? [] : week.data.swaps}
              onOpen={openPlayer}
            />
          )}

          {/* Shown beside the lineups when there is an opponent, since the
              swaps then have no card of their own to live in. */}
          {!week.data.actions && week.data.opponent && week.data.swaps.length > 0 && (
            <Card>
              <CardHeader>
                <span>Changes the projections imply</span>
              </CardHeader>
              {week.data.swaps.map((swap) => (
                <div
                  key={swap.start}
                  className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-t border-border px-4 py-2.5 text-[13px] first:border-t-0"
                >
                  <span className="font-medium">{swap.start}</span>
                  <span className="text-muted-foreground">for {swap.out || "an empty place"}</span>
                  <span className="ml-auto font-mono text-[12px] text-ok">{swap.gain}</span>
                </div>
              ))}
            </Card>
          )}

          {week.data.boosts && week.data.boosts.stats.length > 0 && (
            <Card>
              <CardHeader>
                <span>{week.data.boosts.title}</span>
                <span>
                  {week.data.boosts.stats.filter((s) => s.tone === "good").length} available
                </span>
              </CardHeader>
              {/* A grid rather than a strip: these are four parallel answers to
                  the same question, and reading down a column beats hunting. */}
              <div className="grid grid-cols-2 gap-x-4 px-4 py-1 sm:grid-cols-4">
                {week.data.boosts.stats.map((boost) => (
                  <div key={boost.label} className="flex flex-col gap-0.5 py-2.5">
                    <span className="truncate font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                      {boost.label}
                    </span>
                    <span
                      className={cn(
                        "truncate text-[13px]",
                        boost.tone === "good" && "font-medium text-ok",
                        boost.tone === "warning" && "text-warn",
                        boost.tone === "neutral" && "text-muted-foreground",
                      )}
                    >
                      {boost.value}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {week.data.fixtures.length > 0 && (
            <Card>
              <CardHeader>
                <span>Watch out for</span>
              </CardHeader>
              <div className="flex flex-col">
                {week.data.fixtures.map((fixture) => (
                  <div
                    key={fixture.label}
                    className="flex items-baseline gap-3 border-t border-border px-4 py-2 text-[13px] first:border-t-0"
                  >
                    <span className="w-14 shrink-0 font-mono text-[11px] text-muted-foreground">{fixture.label}</span>
                    <span className={fixture.tone === "warning" ? "text-warn" : "text-muted-foreground"}>
                      {fixture.value}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {!week.data.opponent && (
            <Badge variant="muted" appearance="label">
              No head-to-head fixture this week
            </Badge>
          )}
        </div>
      )}
      {drawer}
    </>
  );
}

/** Said in words as well as color, so the order survives without the hue. */
const URGENCY: Record<Urgency, { label: string; variant: "warn" | "info" | "muted" }> = {
  now: { label: "Now", variant: "warn" },
  soon: { label: "Soon", variant: "info" },
  later: { label: "Later", variant: "muted" },
};

/**
 * What to do about the week, most urgent first.
 *
 * At the top because it is the reason to open the page: the lineups below are
 * the evidence, and this is the conclusion. Each row names its deadline where
 * the platform has one and opens the player it turns on. An empty list is
 * said out loud — "nothing to do" is an answer worth having, and a missing
 * card would look the same as a page that never checked.
 */
function ActionList({ actions, onOpen }: { actions: Action[]; onOpen: (id: string) => void }) {
  return (
    <Card>
      <CardHeader>
        <span>To do</span>
        {actions.length > 0 && <span>{actions.length}</span>}
      </CardHeader>
      {actions.length === 0 ? (
        <p className="px-4 py-3 text-[13px] text-muted-foreground">Nothing to do — your lineup is set for the week.</p>
      ) : (
        <ol className="flex flex-col">
          {actions.map((action) => {
            const open = action.player_id ? () => onOpen(action.player_id) : undefined;
            const urgency = URGENCY[action.urgency];
            return (
              <li
                key={`${action.kind}-${action.title}`}
                onClick={open}
                onKeyDown={open && ((e) => e.key === "Enter" && open())}
                tabIndex={open ? 0 : undefined}
                role={open ? "button" : undefined}
                className={cn(
                  "flex items-start gap-3 border-t border-border px-4 py-3 first:border-t-0",
                  open && "cursor-pointer hover:bg-muted",
                )}
              >
                <Badge variant={urgency.variant} appearance="status" className="mt-0.5 w-16 shrink-0">
                  {urgency.label}
                </Badge>
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] font-medium">{action.title}</div>
                  <div className="mt-0.5 text-[12.5px] text-muted-foreground">{action.reason}</div>
                  {action.evidence.length > 0 && (
                    <ul className="mt-1.5 flex flex-col gap-1">
                      {action.evidence.map((line) => (
                        <li key={line.label} className="flex items-baseline gap-2 text-[12px] text-muted-foreground">
                          {/* The rank is in the words; the dot only lets a
                              soft or tough matchup be found at a glance. */}
                          <span
                            aria-hidden
                            className={cn(
                              "size-1.5 shrink-0 -translate-y-px rounded-full bg-border",
                              line.tone === "good" && "bg-ok",
                              line.tone === "warning" && "bg-warn",
                            )}
                          />
                          <span>
                            <span className="font-medium text-foreground">{line.label}</span> {line.value}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                {action.when && (
                  <span className="shrink-0 pt-0.5 text-right font-mono text-[11px] text-muted-foreground">
                    {action.when}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
