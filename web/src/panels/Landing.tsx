import { useQueries } from "@tanstack/react-query";
import { ChevronRight, Trophy } from "lucide-react";
import { api, type League, type Competition } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { ExternalLink } from "@/components/ui/external-link";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { m } from "motion/react";
import { list, listItem } from "@/lib/motion";
import { YahooLoginButton } from "@/components/ui/error-note";

/**
 * What the app opens on: every league you are in, across every competition.
 *
 * The alternative — dropping straight into whichever competition happened to be
 * configured first — silently picks for you, and with three competitions and several
 * leagues each it is picking wrong most of the time.
 */
export function Landing({
  competitions,
  onPick,
}: {
  competitions: Competition[];
  onPick: (competition: Competition, league: League) => void;
}) {
  const configured = competitions.filter((s) => s.configured);

  // One query per competition rather than one combined endpoint: they fail
  // independently — one platform being down must not take the page down — and
  // each is cached under the same key the panels already use. A competition that is
  // not ready is not asked at all; the request could only fail, and the reason
  // is already known.
  const results = useQueries({
    queries: configured.map((competition) => ({
      queryKey: ["leagues", competition.key],
      queryFn: () => api.leagues(competition.key),
      enabled: competition.ready,
    })),
  });

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <div className="flex items-center gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Trophy className="size-5" strokeWidth={2.25} aria-hidden />
        </span>
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">The Front Office</h1>
          <p className="font-mono text-[12px] text-muted-foreground">Pick a league</p>
        </div>
      </div>

      <m.div variants={list} initial="hidden" animate="shown" className="mt-8 flex flex-col gap-4">
        {configured.map((competition, i) => {
          const result = results[i];
          return (
            <m.div key={competition.key} variants={listItem}>
            <Card>
              <CardHeader>
                <span>{competition.label}</span>
                {competition.ready && result?.isSuccess && (
                  <span>
                    {result.data.length} {result.data.length === 1 ? "league" : "leagues"}
                  </span>
                )}
                {!competition.ready && (
                  <Badge variant="warn" appearance="status">
                    unavailable
                  </Badge>
                )}
              </CardHeader>

              {/* Stated once, with the action, rather than left to fail on the
                  first click into the competition. */}
              {!competition.ready && (
                <div className="flex flex-col items-start gap-3 px-4 py-3">
                  <p className="max-w-[70ch] text-[13px] leading-relaxed text-muted-foreground">
                    {competition.blocked_reason}
                  </p>
                  {competition.blocked_code === "yahoo_login_required" && <YahooLoginButton />}
                  {competition.blocked_code === "yahoo_not_approved" && (
                    <a
                      href="https://competitions.yahoo.com/developer/access/"
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex h-9 items-center rounded-md border border-border bg-background px-4 text-sm font-medium hover:bg-muted"
                    >
                      Apply for API access
                    </a>
                  )}
                </div>
              )}

              {competition.ready && result?.isLoading && <Skeleton className="m-4 h-14" />}

              {result?.isError && (
                // Shown in place rather than as a page-level failure: the other
                // competitions are still usable, and this one names its own fix.
                <p className="px-4 py-3 text-[13px] leading-relaxed text-destructive">
                  {(result.error as Error).message}
                </p>
              )}

              {result?.isSuccess && result.data.length === 0 && (
                <p className="px-4 py-3 text-[13px] text-muted-foreground">
                  No leagues this season.
                </p>
              )}

              {result?.data?.map((league) => (
                <button
                  key={league.league_id}
                  onClick={() => onPick(competition, league)}
                  className="flex w-full items-center gap-3 border-t border-border px-4 py-3 text-left transition-colors hover:bg-muted"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-display text-[15px] font-semibold tracking-tight">
                      {league.name}
                    </div>
                    {league.detail && (
                      <div className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
                        {league.detail}
                      </div>
                    )}
                  </div>
                  {/* Straight to the platform, for when you already know what
                      you came to do and this app is not it. */}
                  <ExternalLink href={league.url} label={`Open ${league.name} on the platform`} />
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                </button>
              ))}
            </Card>
            </m.div>
          );
        })}
      </m.div>

      {competitions.some((s) => !s.configured) && (
        <p className="mt-6 text-[13px] text-muted-foreground">
          {competitions
            .filter((s) => !s.configured)
            .map((s) => s.label)
            .join(" and ")}{" "}
          {competitions.filter((s) => !s.configured).length === 1 ? "is" : "are"} not configured — add
          credentials in Settings.
        </p>
      )}
    </div>
  );
}
