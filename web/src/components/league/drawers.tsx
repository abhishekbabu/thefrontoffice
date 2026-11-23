import { useState } from "react";
import type { Competition, League } from "@/lib/types";
import type { Back } from "@/components/ui/overlays/dialog";
import { ComparisonDrawer } from "@/components/league/compare";
import { type Comparing } from "@/lib/comparing";
import { PlayerPanel } from "@/components/league/player";

type Open = ({ kind: "player"; id: string } | ({ kind: "compare" } & Comparing)) & { back?: Back };

/**
 * A page's drawers, and the one piece of state that opens them: a player, or
 * players side by side.
 *
 * One shows at a time. Opening a player from a comparison swaps the
 * comparison out, and his drawer's Back link brings it back; a comparison
 * opened from a move on a player's history does the same for the move.
 *
 * Every table in the app opens a player, and each panel was wiring the same
 * three things by hand: a nullable id, the callback that sets it, and a
 * drawer whose props were identical everywhere. Forgetting the `onClose` half
 * leaves a drawer that opens and never shuts, which is exactly the kind of
 * mistake a repeated block invites.
 */
export function useDrawers(competition: Competition, league: League) {
  const [open, setOpen] = useState<Open | null>(null);
  const comparing = open?.kind === "compare" ? open : null;

  // Back out of a drawer: shut it, then reopen whatever it replaced.
  const back = open?.back && {
    label: open.back.label,
    onBack: () => {
      setOpen(null);

      open.back!.onBack();
    },
  };

  const openComparison = (with_: Comparing, from?: Back) => setOpen({ kind: "compare", ...with_, back: from });

  return {
    /** Open a player; `back` is the drawer he replaced, which his own offers to return to. */
    openPlayer: (id: string, from?: Back) => setOpen({ kind: "player", id, back: from }),
    /** Open players side by side; one is enough to open him alone. */
    openComparison: (with_: Comparing, from?: Back) =>
      with_.ids.length === 1 ? setOpen({ kind: "player", id: with_.ids[0]!, back: from }) : openComparison(with_, from),
    drawer: (
      <>
        <PlayerPanel
          competition={competition.key}
          league={league.league_id}
          playerId={open?.kind === "player" ? open.id : null}
          back={open?.kind === "player" ? back : undefined}
          onClose={() => setOpen(null)}
          onPick={(id, from) => setOpen({ kind: "player", id, back: from })}
          onCompare={(ids, from) => openComparison({ ids }, from)}
        />
        <ComparisonDrawer
          competition={competition.key}
          league={league.league_id}
          comparing={comparing}
          back={comparing ? back : undefined}
          onClose={() => setOpen(null)}
          onOpenPlayer={(id, label) =>
            setOpen({ kind: "player", id, back: { label, onBack: () => setOpen(comparing) } })
          }
        />
      </>
    ),
  };
}
