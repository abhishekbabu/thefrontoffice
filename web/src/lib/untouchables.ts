import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { PlayerCard } from "@/lib/types";

/**
 * The players on your roster you will not let go, in one league, and the way to mark one.
 *
 * Kept on the server, because the server is what chooses drops, trade ideas
 * and transfers: a mark changes what the week's to-do list, the trades and
 * the weeks ahead say, so those are read again once it is made.
 */
export function useUntouchables(competition: string, league: string, enabled = true) {
  const queryClient = useQueryClient();
  const leagueApi = api.league(competition, league);

  const marked = useQuery({
    queryKey: keys.untouchables(competition, league),
    queryFn: leagueApi.untouchables,
    enabled,
  });

  const mark = useMutation({
    mutationFn: leagueApi.markUntouchable,
    onSuccess: (now) => {
      queryClient.setQueryData(keys.untouchables(competition, league), now);

      for (const stale of [keys.week(competition, league), keys.trades(competition, league), keys.outlook(competition, league)]) {
        void queryClient.invalidateQueries({ queryKey: stale });
      }
    },
  });

  const ids = new Set(marked.data?.player_ids ?? []);

  return {
    has: (playerId: string) => ids.has(playerId),
    toggle: (playerId: string) => mark.mutate({ player_id: playerId, untouchable: !ids.has(playerId) }),
    pending: mark.isPending,
    failed: mark.isError,
  };
}

/**
 * Your own roster, read as the roster page first reads it: in the competition's
 * own order, under the same key, so a drawer opened from there asks nothing again.
 */
export function useOwnRoster(competition: string, league: string, enabled = true) {
  return useQuery<PlayerCard[], Error>({
    queryKey: [...keys.roster(competition, league), null],
    queryFn: () => api.league(competition, league).roster(),
    enabled,
  });
}
