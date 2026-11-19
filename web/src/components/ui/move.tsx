import { GitCompareArrows } from "lucide-react";
import { Meta } from "@/components/ui/label";
import { useNavigate } from "react-router-dom";
import type { ActivityRow } from "@/lib/api";
import { MAX_COMPARED, useCompared } from "@/lib/compare";
import { href } from "@/lib/route";
import { Badge } from "@/components/ui/badge";
import { IconButton } from "@/components/ui/icon-button";
import { ListCard, ListRow } from "@/components/ui/list";
import { SlideOver, SlideOverHeader, type Back } from "@/components/ui/dialog";

/**
 * One league move on one line: when, who, what, and "+A, -B". Read the same in
 * the league's activity and on a player's history, and opens the same drawer.
 */
export function MoveRow({ move, onOpen }: { move: ActivityRow; onOpen?: (move: ActivityRow) => void }) {
  return (
    <ListRow current={move.is_mine} onClick={onOpen && move.moves.length ? () => onOpen(move) : undefined}>
      <Meta className="w-16 shrink-0">{move.when}</Meta>
      {/* Gives way on a narrow screen rather than pushing the badge out of the card. */}
      <span className="w-48 min-w-0 truncate">{move.who}</span>
      <Badge variant="muted" appearance="label" className="shrink-0">
        {move.what}
      </Badge>
      <Meta className="min-w-0 flex-1 truncate">{move.detail}</Meta>
      {move.bid && <span className="shrink-0 font-mono text-[11px] tabular-nums">{move.bid}</span>}
    </ListRow>
  );
}

/**
 * A move in full: who got whom, and a way to compare its players.
 *
 * A player opened from it stacks over it, so closing him returns here.
 */
export function MoveDrawer({
  move,
  competition,
  league,
  back,
  onClose,
  onOpenPlayer,
}: {
  move: ActivityRow | null;
  competition: string;
  league: string;
  /** The drawer this one replaced, where there was one. */
  back?: Back;
  onClose: () => void;
  /** Swap to a player; the caller makes this move what his drawer goes back to. */
  onOpenPlayer: (id: string) => void;
}) {
  const compared = useCompared(competition, league);
  const navigate = useNavigate();
  return (
    <SlideOver
      open={move !== null}
      onClose={onClose}
      label={move ? `${move.what} by ${move.who}` : "Move"}
      className="max-w-lg border-l border-border"
    >
      {move && (
        <MoveDetail
          move={move}
          back={back}
          onClose={onClose}
          onOpen={onOpenPlayer}
          onCompare={() => {
            compared.set(move.moves.map((m) => m.player_id).filter(Boolean));
            onClose();
            navigate(href(competition, league, "compare"));
          }}
        />
      )}
    </SlideOver>
  );
}

function MoveDetail({
  move,
  back,
  onClose,
  onOpen,
  onCompare,
}: {
  move: ActivityRow;
  back?: Back;
  onClose: () => void;
  onOpen: (id: string) => void;
  onCompare: () => void;
}) {
  const players = new Set(move.moves.map((m) => m.player_id).filter(Boolean)).size;
  return (
    <>
      <SlideOverHeader
        title={`${move.what} · ${move.who}`}
        meta={[move.when, move.bid && `won for ${move.bid}`].filter(Boolean).join(" · ")}
        back={back}
        onClose={onClose}
      >
        {players > 1 && (
          <IconButton
            label={players > MAX_COMPARED ? `Compare the first ${MAX_COMPARED}` : "Compare these players"}
            icon={<GitCompareArrows />}
            onClick={onCompare}
          />
        )}
      </SlideOverHeader>
      <div className="flex flex-col gap-4 p-5">
        {sections(move).map(({ title, moves }) => (
          <ListCard key={title} title={title} count={`${moves.length}`}>
            {moves.map((m) => (
              <ListRow
                key={`${m.change}-${m.player_id || m.player}`}
                onClick={m.player_id ? () => onOpen(m.player_id) : undefined}
              >
                {/* Said, not only colored: which way he went is the whole row. */}
                <Badge variant={m.change === "added" ? "ok" : "fail"} appearance="label" className="shrink-0">
                  {m.change === "added" ? "+" : "−"}
                </Badge>
                <span className="min-w-0 flex-1 truncate">{m.player}</span>
                <Meta className="shrink-0">
                  {[m.position, m.team].filter(Boolean).join(" · ")}
                </Meta>
              </ListRow>
            ))}
          </ListCard>
        ))}
      </div>
    </>
  );
}

/**
 * A move's players in the sections that make it readable.
 *
 * A trade reads by who got whom — one section per manager, holding the players
 * his roster took — since "added" and "dropped" each mix both sides. Anything
 * one manager did alone reads as what he added and what he let go.
 */
export function sections(move: ActivityRow): { title: string; moves: ActivityRow["moves"] }[] {
  const managers = [...new Set(move.moves.filter((m) => m.change === "added").map((m) => m.manager))];
  if (managers.length > 1) {
    return managers.map((manager) => ({
      title: `To ${manager}`,
      moves: move.moves.filter((m) => m.change === "added" && m.manager === manager),
    }));
  }
  return [
    { title: "Added", moves: move.moves.filter((m) => m.change === "added") },
    { title: "Dropped", moves: move.moves.filter((m) => m.change === "dropped") },
  ].filter((section) => section.moves.length > 0);
}

/** What a player opened from `move` goes back to: the move, reopened by `reopen`. */
export function backTo(move: ActivityRow, reopen: () => void): Back {
  return { label: `${move.what} · ${move.who}`, onBack: reopen };
}
