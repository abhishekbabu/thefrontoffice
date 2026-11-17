import type { PlayerDetail } from "@/lib/api";

/** A player as the drawer receives him, with nothing in it but what a test sets. */
export function playerDetail(extra: Partial<PlayerDetail> = {}): PlayerDetail {
  return {
    player_id: "1",
    name: "Player",
    position: "WR",
    team: "DAL",
    team_name: "",
    team_logo_url: "",
    headline: "",
    headline_label: "",
    note: "",
    url: "",
    image_url: "",
    tone: "neutral",
    rank: "",
    owner: "",
    tabs: [],
    groups: [],
    tables: [],
    moves: [],
    moves_tab: "",
    ...extra,
  };
}
