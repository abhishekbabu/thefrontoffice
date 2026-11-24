import type { Competition, League } from "@/lib/types";

/** A competition as the app receives it, offering nothing a test does not switch on. */
export function competitionOf(extra: Partial<Competition> & Pick<Competition, "key">): Competition {
  return {
    sport: "",
    competition: "",
    platform: "",
    label: "",
    name: "",
    week_word: "week",
    judges_wire: false,
    plans_weeks: false,
    browses_weeks: false,
    browses_days: false,
    finds_trades: false,
    searches_players: false,
    refreshes: false,
    syncs: false,
    configured: true,
    requires: "",
    blocked: null,
    ...extra,
  };
}

/** A league as the app receives it. */
export function leagueOf(league_id: string): League {
  return { league_id, name: "", detail: "", url: "" };
}
