import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Undo2 } from "lucide-react";
import type { WeekRange } from "@/lib/api";
import { IconButton } from "@/components/ui/icon-button";
import { Badge } from "@/components/ui/badge";

/**
 * Paging through the season a week at a time: a step either way, and the way back to the week being played.
 *
 * The arrow keys do the same, as does a sideways swipe on whatever `useSwipe`
 * is attached to. Each control says which week it goes to, because "next"
 * alone does not say whether next is the week you want.
 */
export function WeekStepper({ range, onStep }: { range: WeekRange; onStep: (week: number) => void }) {
  const { week, current, first, last } = range;
  useArrowKeys(
    () => week > first && onStep(week - 1),
    () => week < last && onStep(week + 1),
  );
  return (
    <div className="flex items-center gap-1" role="group" aria-label="Week">
      <IconButton
        label={`Week ${week - 1}`}
        icon={<ChevronLeft />}
        onClick={() => onStep(week - 1)}
        disabled={week <= first}
      />
      <span className="min-w-16 text-center font-mono text-[12px] tabular-nums" aria-live="polite">
        Week {week}
      </span>
      <IconButton
        label={`Week ${week + 1}`}
        icon={<ChevronRight />}
        onClick={() => onStep(week + 1)}
        disabled={week >= last}
      />
      {/* Said, not only implied by the controls: which week this is relative to now. */}
      {week === current ? (
        <Badge variant="muted" appearance="label">
          this week
        </Badge>
      ) : (
        <IconButton label={`Back to this week (week ${current})`} icon={<Undo2 />} onClick={() => onStep(current)} />
      )}
    </div>
  );
}

/** Whether a key press belongs to something being typed into, which an arrow key must stay with. */
function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

function useArrowKeys(onLeft: () => void, onRight: () => void) {
  // Read through a ref so the listener is attached once, not on every week.
  const handlers = useRef({ onLeft, onRight });
  handlers.current = { onLeft, onRight };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || typing(event.target)) return;
      if (event.key === "ArrowLeft") handlers.current.onLeft();
      if (event.key === "ArrowRight") handlers.current.onRight();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** How far a finger has to travel sideways, in pixels, before it is a swipe rather than a wobble. */
export const SWIPE_DISTANCE = 60;

/**
 * A sideways swipe on the element the returned handlers are spread onto: left for the next week, right for the last.
 *
 * Touch only, and only where the movement is mostly sideways: a mouse drag is
 * selecting text, and a diagonal flick is somebody scrolling.
 */
export function useSwipe(onNext: () => void, onPrevious: () => void) {
  const start = useRef<{ x: number; y: number } | null>(null);
  return {
    onPointerDown: (event: React.PointerEvent) => {
      start.current = event.pointerType === "touch" ? { x: event.clientX, y: event.clientY } : null;
    },
    onPointerUp: (event: React.PointerEvent) => {
      const from = start.current;
      start.current = null;
      if (!from) return;
      const dx = event.clientX - from.x;
      const dy = event.clientY - from.y;
      if (Math.abs(dx) < SWIPE_DISTANCE || Math.abs(dx) < 2 * Math.abs(dy)) return;
      if (dx < 0) onNext();
      else onPrevious();
    },
  };
}

/**
 * Which week a page shows, named in its address as `?week=7`, against the season's `range`.
 *
 * The week being played leaves the parameter off, so its address is the page's
 * own. A week outside the season is the week being played: an address
 * somebody trimmed is not an error worth a page. Stepping pushes a history
 * entry, so Back returns through the weeks visited.
 */
export function useWeekParam(range: WeekRange | undefined) {
  const [params, setParams] = useSearchParams();
  const asked = Number(params.get("week")) || null;
  const browsing =
    range && asked !== null && asked !== range.current && asked >= range.first && asked <= range.last ? asked : null;
  const step = (to: number) => setParams(range && to !== range.current ? { week: String(to) } : {});
  const shown = range ? { ...range, week: browsing ?? range.current } : undefined;
  const swipe = useSwipe(
    () => shown && shown.week < shown.last && step(shown.week + 1),
    () => shown && shown.week > shown.first && step(shown.week - 1),
  );
  return { browsing, shown, step, swipe };
}
