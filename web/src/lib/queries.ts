import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Every query key, spelled once.
 *
 * A key is how two components share one answer and how a mutation says which
 * answers it changed. Spelled inline it drifts — the capabilities were asked
 * under one key in four places, one typo from four requests — and an
 * invalidation that misspells a key silently refreshes nothing.
 *
 * A league's keys all start with `league(...)`, so dropping everything about
 * one league is one invalidation.
 */
export const keys = {
  competitions: ["competitions"] as const,
  capabilities: ["capabilities"] as const,
  settings: ["settings"] as const,
  yahooLogin: ["yahoo-login"] as const,
  leagues: (competition: string) => ["leagues", competition] as const,
  league: (competition: string, league: string) => ["league", competition, league] as const,
  summary: (competition: string, league: string) => [...keys.league(competition, league), "summary"] as const,
  judgment: (competition: string, league: string) => [...keys.league(competition, league), "judgment"] as const,
  roster: (competition: string, league: string) => [...keys.league(competition, league), "roster"] as const,
  schedule: (competition: string, league: string) => [...keys.league(competition, league), "schedule"] as const,
  teams: (competition: string, league: string) => [...keys.league(competition, league), "teams"] as const,
  teamRoster: (competition: string, league: string, team: string | undefined) =>
    [...keys.league(competition, league), "team-roster", team] as const,
  weeksAhead: (competition: string, league: string) => [...keys.league(competition, league), "weeks-ahead"] as const,
  trades: (competition: string, league: string) => [...keys.league(competition, league), "trades"] as const,
  player: (competition: string, league: string, player: string) =>
    [...keys.league(competition, league), "player", player] as const,
  freeAgents: (competition: string, league: string) => [...keys.league(competition, league), "free-agents"] as const,
  freeAgentCalls: (competition: string, league: string) =>
    [...keys.league(competition, league), "free-agent-calls"] as const,
  thread: (competition: string, league: string, kind: string, key: string) =>
    [...keys.league(competition, league), "thread", kind, key] as const,
};

/** What this installation can do: whether a model is configured, and the engines' limits. */
export function useCapabilities() {
  return useQuery({ queryKey: keys.capabilities, queryFn: api.capabilities });
}
