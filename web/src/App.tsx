import { Suspense, lazy, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Moon, Settings, Sun, Trophy } from "lucide-react";
import { AnimatePresence, m } from "motion/react";
import { api, type League, type Competition } from "@/lib/api";
import { keys } from "@/lib/queries";
import { DEFAULT_VIEW, LANDING, SETTINGS, VIEWS, type View, href, parse } from "@/lib/route";
import { useTheme } from "@/lib/useTheme";
import { IconButton } from "@/components/ui/icon-button";
import { Tooltip } from "@/components/ui/tooltip";
import { rise } from "@/lib/motion";
import { Skeleton } from "@/components/ui/skeleton";
import { Empty, Loading } from "@/components/ui/state";
import { ErrorNote } from "@/components/ui/error-note";
import { cn } from "@/lib/utils";
import { Label } from "@/components/ui/label";

// Each page loads when it is first opened rather than in the first download:
// the entry bundle is what every visit waits on, and it was carrying all six.
const ScoutPanel = lazy(() => import("@/panels/Scout").then((m) => ({ default: m.ScoutPanel })));
const LeaguePanel = lazy(() => import("@/panels/LeaguePanel").then((m) => ({ default: m.LeaguePanel })));
const FreeAgentsPanel = lazy(() => import("@/panels/FreeAgents").then((m) => ({ default: m.FreeAgentsPanel })));
const TeamPanel = lazy(() => import("@/panels/Team").then((m) => ({ default: m.TeamPanel })));
const SettingsPanel = lazy(() => import("@/panels/Settings").then((m) => ({ default: m.SettingsPanel })));
const Landing = lazy(() => import("@/panels/Landing").then((m) => ({ default: m.Landing })));

type PanelProps = { competition: Competition; league: League };

/**
 * Every view in one table: what the rail calls it and what renders it.
 * `Record<View, …>` makes a missing entry a type error rather than a view that
 * silently never renders.
 */
const PANELS: Record<View, { label: string; Panel: (props: PanelProps) => React.ReactNode }> = {
  week: { label: "This week", Panel: ScoutPanel },
  league: { label: "League", Panel: LeaguePanel },
  team: { label: "My team", Panel: TeamPanel },
  "free-agents": { label: "Free agents", Panel: FreeAgentsPanel },
};

export default function App() {
  const { mode, setMode } = useTheme();
  const navigate = useNavigate();
  const path = useLocation().pathname;
  const route = parse(path);

  const competitions = useQuery({ queryKey: keys.competitions, queryFn: api.competitions });

  // How many platforms carry each sport, so the rail names the platform only
  // where it distinguishes something.
  const sportCounts = (competitions.data ?? []).reduce<Record<string, number>>((counts, s) => {
    counts[s.sport] = (counts[s.sport] ?? 0) + 1;
    return counts;
  }, {});
  // Ready, not merely configured: credentials being set says nothing about
  // whether a platform will actually answer.
  const usable = (competitions.data ?? []).filter((s) => s.ready);
  // No fallback to the first usable competition: until one is chosen the
  // landing page is what shows, and choosing for the user is what it avoids.
  const active: Competition | undefined =
    route.page === "competition" ? usable.find((s) => s.key === route.competition) : undefined;

  const leagues = useQuery({
    queryKey: keys.leagues(active?.key ?? ""),
    queryFn: () => api.leagues(active!.key),
    enabled: Boolean(active),
  });
  // Falling back to the first league is what makes /nfl-sleeper a real address;
  // the effect below then writes the one it resolved into the URL.
  const league: League | undefined =
    route.page === "competition"
      ? ((leagues.data ?? []).find((l) => l.league_id === route.leagueId) ?? leagues.data?.[0])
      : undefined;

  const view = route.page === "competition" ? route.view : DEFAULT_VIEW;

  // Make the address say what is on screen.
  //
  // One comparison against the canonical link rather than a branch per way of
  // being wrong: it covers the league that /nfl-sleeper resolved to, a view
  // this competition does not offer, and /a/b/week spelled the long way. All
  // by replacing, not pushing — being corrected off an address that does not
  // name a page is not a move you should have to press Back through.
  useEffect(() => {
    if (route.page !== "competition") return;
    if (competitions.data && !active) {
      // A competition nobody can play: a typo, or one whose credentials have
      // gone. Only once the list has arrived — before that they all look alike.
      navigate(LANDING, { replace: true });
      return;
    }
    if (!active || !league) return;
    const settled = href(active.key, league.league_id, view);
    if (settled !== path) navigate(settled, { replace: true });
  }, [route.page, path, competitions.data, active, league, view, navigate]);

  /**
   * The column beside the rail: one `if` per state, rather than a ternary
   * chain seven levels deep inside the layout.
   *
   * Called, not rendered as `<Shell />`. A component declared inside another
   * is a new function on every render, so React sees a new element type and
   * remounts the whole subtree — every panel would refetch and lose its
   * scroll position each time anything in the shell changed.
   */
  function shell() {
    if (route.page === "settings") return <SettingsPanel onBack={() => navigate(LANDING)} />;
    if (competitions.isSuccess && usable.length === 0) return <NothingConnected competitions={competitions.data} />;

    if (route.page !== "competition") {
      return competitions.isSuccess ? (
        <Landing competitions={competitions.data} onPick={(picked, l) => navigate(href(picked.key, l.league_id))} />
      ) : (
        <Loading />
      );
    }

    if (!active || !league) return leagues.isError ? <ErrorNote error={leagues.error} /> : <Loading />;

    // Keyed so a competition or league change remounts the panel. Without it
    // the panel keeps the report it already fetched, and the previous
    // competition's analysis renders under the new league's name — a stale FPL
    // report headed "Huge Euge RR FF", with FPL's figures in the strip.
    const { Panel } = PANELS[view];
    return (
      <m.div key={`${active.key}:${league.league_id}:${view}`} variants={rise} initial="hidden" animate="shown">
        <Panel competition={active} league={league} />
      </m.div>
    );
  }

  return (
    // Fixed to the viewport, with each column scrolling on its own. A single
    // page scroll takes the rail with it, so the competition you are on and the
    // way back leave the screen exactly when a long table makes you want them.
    <div className="grid h-full grid-cols-[13rem_minmax(0,1fr)] overflow-hidden">
      <nav className="flex flex-col gap-6 overflow-y-auto border-r border-border bg-card px-3 py-4">
        <Link
          to={LANDING}
          aria-label="Back to all leagues"
          className="flex items-center gap-2.5 rounded-md px-1 py-1 text-left transition-colors hover:bg-muted"
        >
          <span className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-primary text-primary-foreground">
            <Trophy className="size-3.5" strokeWidth={2.25} aria-hidden />
          </span>
          <span className="font-display text-[15px] font-semibold tracking-tight">The Front Office</span>
        </Link>

        {/* Competition, not sport: these are the NBA, the NFL and the Premier
            League. "League" is taken by the group below, which holds the
            fantasy leagues you actually play in. */}
        <Group label="Competition">
          {competitions.isLoading && <Skeleton className="mx-2 h-7" />}
          {(competitions.data ?? []).map((s) => {
            // Two platforms under one sport need telling apart; one does not.
            const label = (sportCounts[s.sport] ?? 0) > 1 ? s.label : s.name;
            return s.ready ? (
              <RailLink key={s.key} to={`/${s.key}`} active={s.key === active?.key}>
                {label}
              </RailLink>
            ) : (
              <RailBlocked key={s.key} reason={s.blocked_reason}>
                {label}
                <span className="font-mono text-[10px] opacity-60">{s.configured ? "blocked" : "off"}</span>
              </RailBlocked>
            );
          })}
        </Group>

        {/* Only once there is a league to address: a tab that cannot be linked
            to yet would render as a control that does nothing. */}
        {active && league && (
          <Group label="View">
            {VIEWS.map((v) => (
              <RailLink key={v} to={href(active.key, league.league_id, v)} active={v === view}>
                {PANELS[v].label}
              </RailLink>
            ))}
          </Group>
        )}

        {active && (leagues.data?.length ?? 0) > 1 && (
          <Group label="League">
            {leagues.data!.map((l) => (
              <RailLink
                key={l.league_id}
                to={href(active.key, l.league_id, view)}
                active={l.league_id === league?.league_id}
              >
                <span className="truncate">{l.name}</span>
              </RailLink>
            ))}
          </Group>
        )}

        <div className="mt-auto flex items-center gap-1">
          <RailLink className="flex-1" to={SETTINGS} active={route.page === "settings"}>
            <span className="flex items-center gap-2">
              <Settings className="size-3.5" aria-hidden />
              Settings
            </span>
          </RailLink>
          <IconButton
            label={mode === "dark" ? "Switch to light" : "Switch to dark"}
            side="top"
            icon={mode === "dark" ? <Sun /> : <Moon />}
            onClick={() => setMode(mode === "dark" ? "light" : "dark")}
          />
        </div>
      </nav>

      <main className="min-w-0 overflow-y-auto">
        {/* One presence around the whole column, keyed on the page. Settings is
            a place you go and come back from, so it earns the same in-and-out
            transition as every other view. */}
        <AnimatePresence mode="wait">
          <m.div
            key={route.page === "settings" ? "settings" : "app"}
            variants={rise}
            initial="hidden"
            animate="shown"
            exit="gone"
          >
            {/* While a page's code arrives: the shell's own skeleton, the one it
                already shows while the leagues load. */}
            <Suspense fallback={<Loading />}>{shell()}</Suspense>
          </m.div>
        </AnimatePresence>
      </main>
    </div>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <Label as="p" className="px-2 pb-1.5">
        {label}
      </Label>
      {children}
    </div>
  );
}

/** One look for everything in the rail, whether it navigates or not. */
function railItem(active?: boolean, disabled?: boolean, className?: string) {
  return cn(
    "flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[13.5px] transition-colors",
    active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-muted",
    disabled && "cursor-not-allowed opacity-40 hover:bg-transparent",
    className,
  );
}

/**
 * A rail item that goes somewhere, which is most of them.
 *
 * A real link rather than a button that navigates: every view has an address
 * now, and an address you cannot open in a new tab, middle-click or preview on
 * hover is only half of one.
 */
function RailLink({
  to,
  active,
  className,
  children,
}: {
  to: string;
  active?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link to={to} className={railItem(active, false, className)} aria-current={active ? "page" : undefined}>
      {children}
    </Link>
  );
}

/** A rail item that goes nowhere — a competition you cannot play — and why, on hover. */
function RailBlocked({ reason, children }: { reason: string; children: React.ReactNode }) {
  // A disabled control cannot be hovered in every browser, so the reason is
  // wrapped rather than attached — and Radix keeps it reachable by keyboard.
  return (
    <Tooltip label={reason} side="right">
      <span className="cursor-not-allowed">
        <button disabled className={railItem(false, true)}>
          {children}
        </button>
      </span>
    </Tooltip>
  );
}

/** Nothing is configured — say what to set rather than showing an empty shell. */
function NothingConnected({ competitions }: { competitions: Competition[] }) {
  return (
    <div className="mx-auto max-w-xl p-5">
      <Empty
        title="Nothing connected yet"
        detail="Set one of these in Settings, or in .env directly."
        action={
          <ul className="flex w-full flex-col gap-2">
            {competitions.map((s) => (
              <li key={s.key} className="flex items-baseline justify-between gap-4 border-b border-border py-2 text-sm">
                <span>{s.label}</span>
                <code className="font-mono text-[12px] text-muted-foreground">{s.requires}</code>
              </li>
            ))}
          </ul>
        }
      />
    </div>
  );
}
