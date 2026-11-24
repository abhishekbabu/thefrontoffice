import { Lock, LockOpen } from "lucide-react";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Hint } from "@/components/ui/overlays/tooltip";
import { useOwnRoster, useUntouchables } from "@/lib/untouchables";

/**
 * Mark one of your players untouchable, or clear the mark: never a drop, a
 * trade away or a sale. Offered for your own players only — a mark on anyone
 * else's would honour nothing. The lock's shape and the label carry the state.
 */
export function UntouchableToggle({
  competition,
  league,
  playerId,
}: {
  competition: string;
  league: string;
  playerId: string;
}) {
  const mine = useOwnRoster(competition, league, Boolean(playerId)).data?.some((p) => p.player_id === playerId) ?? false;
  const untouchable = useUntouchables(competition, league, mine);

  if (!mine) return null;

  const on = untouchable.has(playerId);

  return (
    <IconButton
      label={untouchable.failed ? "Not saved: try again" : on ? "Untouchable: clear" : "Mark untouchable"}
      icon={on ? <Lock /> : <LockOpen />}
      aria-pressed={on}
      disabled={untouchable.pending}
      onClick={() => untouchable.toggle(playerId)}
    />
  );
}

/** The lock beside the name of a player you marked untouchable, wherever your players are listed. */
export function UntouchableLock() {
  return (
    <Hint label="Untouchable" name="Untouchable" className="inline-flex shrink-0">
      <Lock aria-hidden className="size-3 text-muted-foreground" />
    </Hint>
  );
}
