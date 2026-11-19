import type { PlayerComparison, PlayerDetail } from "@/lib/api";

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
    deferred: [],
    ...extra,
  };
}

/** Two players side by side, as a comparison arrives: an add and the drop it pays for. */
export const REED_WHITE: PlayerComparison = {
  players: [
    playerDetail({ player_id: "p.1", name: "Paul Reed", headline: "12.3" }),
    playerDetail({ player_id: "p.2", name: "Coby White", headline: "4.9" }),
  ],
  tables: [
    {
      title: "This week",
      tab: "",
      columns: ["Paul Reed", "Coby White"],
      rows: [{ label: "Value a game", values: ["12.3", "4.9"], tone: "neutral", better: "higher", best: [0] }],
      absent: "—",
    },
  ],
};
