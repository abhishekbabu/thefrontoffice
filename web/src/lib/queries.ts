import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/** Where every key about one league starts. */
const inLeague = (competition: string, league: string) => ["league", competition, league] as const;

/**
 * Every query key, spelled once.
 *
 * A key is how two components share one answer and how a mutation says which
 * answers it changed. Spelled inline it drifts — the capabilities were asked
 * under one key in four places, one typo from four requests — and an
 * invalidation that misspells a key silently refreshes nothing.
 */
export const keys = {
  competitions: ["competitions"] as const,
  capabilities: ["capabilities"] as const,
  settings: ["settings"] as const,
  login: (platform: string) => ["login", platform] as const,
  leagues: (competition: string) => ["leagues", competition] as const,
  summary: (competition: string, league: string) => [...inLeague(competition, league), "summary"] as const,
  judgment: (competition: string, league: string) => [...inLeague(competition, league), "judgment"] as const,
  roster: (competition: string, league: string) => [...inLeague(competition, league), "roster"] as const,
  schedule: (competition: string, league: string) => [...inLeague(competition, league), "schedule"] as const,
  teams: (competition: string, league: string) => [...inLeague(competition, league), "teams"] as const,
  teamRoster: (competition: string, league: string, team: string | undefined) =>
    [...inLeague(competition, league), "team-roster", team] as const,
  weeksAhead: (competition: string, league: string) => [...inLeague(competition, league), "weeks-ahead"] as const,
  trades: (competition: string, league: string) => [...inLeague(competition, league), "trades"] as const,
  player: (competition: string, league: string, player: string) =>
    [...inLeague(competition, league), "player", player] as const,
  freeAgents: (competition: string, league: string) => [...inLeague(competition, league), "free-agents"] as const,
  freeAgentCalls: (competition: string, league: string) =>
    [...inLeague(competition, league), "free-agent-calls"] as const,
  thread: (competition: string, league: string, kind: string, key: string) =>
    [...inLeague(competition, league), "thread", kind, key] as const,
  turns: (chatId: string) => ["chat", chatId] as const,
};

/** What this installation can do: whether a model is configured, and the engines' limits. */
export function useCapabilities() {
  return useQuery({ queryKey: keys.capabilities, queryFn: api.capabilities });
}
