/** The pages the shell shows beside its rail: each loaded on first open, and how wide each runs. */
import { Component } from "@effect/ui";
import type { Html } from "@effect/ui/html";
import { Empty } from "@/components/ui/state";
import type { Competition } from "@/lib/types";
import type { View } from "@/lib/views";

/**
 * Each page loads when it is first opened rather than in the first download:
 * the entry bundle is what every visit waits on, and it was carrying all of them.
 * The shell indexes it by `View`, so a view added without a page fails to compile.
 */
export const PANELS = {
  matchup: Component.lazy("MatchupPanel", () => import("@/panels/Matchup").then((m) => m.MatchupPanel)),
  schedule: Component.lazy("SchedulePanel", () => import("@/panels/Schedule").then((m) => m.SchedulePanel)),
  fixtures: Component.lazy("FixturesPanel", () => import("@/panels/Fixtures").then((m) => m.FixturesPanel)),
  rosters: Component.lazy("RostersPanel", () => import("@/panels/Rosters").then((m) => m.RostersPanel)),
  trades: Component.lazy("TradesPanel", () => import("@/panels/Trades").then((m) => m.TradesPanel)),
  "free-agents": Component.lazy("FreeAgentsPanel", () => import("@/panels/FreeAgents").then((m) => m.FreeAgentsPanel)),
  activity: Component.lazy("ActivityPanel", () => import("@/panels/Activity").then((m) => m.ActivityPanel)),
  league: Component.lazy("LeaguePanel", () => import("@/panels/LeaguePanel").then((m) => m.LeaguePanel)),
  compare: Component.lazy("ComparePanel", () => import("@/panels/Compare").then((m) => m.ComparePanel)),
};

/** Only where a model is configured, and then after the page it docks beside. */
export const Assistant = Component.lazy("Assistant", () => import("@/components/league/assistant").then((m) => m.Assistant));

export const SettingsPanel = Component.lazy("SettingsPanel", () => import("@/panels/Settings").then((m) => m.SettingsPanel));
export const Landing = Component.lazy("Landing", () => import("@/panels/Landing").then((m) => m.Landing));

/**
 * How wide each view runs (`--page-max` in index.css), by what its content
 * needs: a list or a few-column table keeps a reading width, so a row's
 * figures stay near its name; free agents, fifteen-odd columns that truncate
 * even at full width, take the whole column; the rest run wide, and the
 * matchup goes two-across once there is room. `Record<View, …>` makes a view
 * added without a width fail to compile.
 */
export const WIDTH: Record<View, "reading" | "full" | "wide"> = {
  matchup: "full",
  fixtures: "reading",
  schedule: "reading",
  rosters: "full",
  "free-agents": "wide",
  trades: "full",
  activity: "reading",
  league: "reading",
  compare: "reading",
};

/** Nothing is configured — say what to set rather than showing an empty shell. */
export function NothingConnected<M>(h: Html.H<M>, competitions: readonly Competition[]) {
  return h.div.class("mx-auto max-w-xl p-5").children(
    Empty(h, {
      title: "Nothing connected yet",
      detail: "Set one of these in Settings, or in .env directly.",
      action: [
        h.ul.class("flex w-full flex-col gap-2").children(
          competitions.map((s) =>
            h.li
              .key(s.key)
              .class("flex items-baseline justify-between gap-4 border-b border-border py-2 text-sm")
              .children(
                h.span(s.label),
                h.code.class("font-mono text-[12px] text-muted-foreground").children(s.requires),
              ),
          ),
        ),
      ],
    }),
  );
}
