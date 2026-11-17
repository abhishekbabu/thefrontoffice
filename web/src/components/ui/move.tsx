import { GitCompareArrows } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { ActivityRow } from "@/lib/api";
import { MAX_COMPARED, useCompared } from "@/lib/compare";
import { href } from "@/lib/route";
import { Badge } from "@/components/ui/badge";
import { IconButton } from "@/components/ui/icon-button";
import { ListCard, ListRow } from "@/components/ui/list";
import { SlideOver, SlideOverHeader } from "@/components/ui/dialog";

/**
 * One league move on one line: when, who, what, and "+A, -B". Read the same in
 * the league's activity and on a player's history, and opens the same drawer.
 */
export function MoveRow({ move, onOpen }: { move: ActivityRow; onOpen?: (move: ActivityRow) => void }) {
  return (
    <ListRow current={move.is_mine} onClick={onOpen && move.moves.length ? () => onOpen(move) : undefined}>
      <span className="w-16 shrink-0 font-mono text-[11px] text-muted-foreground">{move.when}</span>
      <span className="w-48 shrink-0 truncate">{move.who}</span>
      <Badge variant="muted" appearance="label" className="shrink-0">
        {move.what}
      </Badge>
      <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-muted-foreground">{move.detail}</span>
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
  onClose,
  onOpenPlayer,
}: {
  move: ActivityRow | null;
  competition: string;
  league: string;
  onClose: () => void;
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
  onClose,
  onOpen,
  onCompare,
}: {
  move: ActivityRow;
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
                <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                  {[m.position, m.team].filter(Boolean).join(" · ")}
                </span>
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
