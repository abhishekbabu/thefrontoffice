import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { m } from "motion/react";
import { stepped } from "@/lib/motion/enter";
import { ChevronLeft, ChevronRight, Undo2 } from "lucide-react";
import type { WeekRange } from "@/lib/types";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Button } from "@/components/ui/controls/button";
import { Badge } from "@/components/ui/badge";

/**
 * Paging through the season a week at a time: a step either way, and the way back to the week being played.
 *
 * The arrow keys do the same, as does a sideways swipe on whatever `useSwipe`
 * is attached to. Each control says which week it goes to, because "next"
 * alone does not say whether next is the week you want.
 *
 * `word` is what the competition calls a round — FPL's are gameweeks — and is
 * said in every label here, so the stepper agrees with the page under it.
 * `keys` off where a finer stepper beside it — a week's days — has the arrows.
 */
export function WeekStepper({
  range,
  onStep,
  word = "week",
  keys = true,
}: {
  range: WeekRange;
  onStep: (week: number) => void;
  word?: string;
  keys?: boolean;
}) {
  const { week, current, first, last } = range;
  const Word = word.charAt(0).toUpperCase() + word.slice(1);

  useArrowKeys(
    () => keys && week > first && onStep(week - 1),
    () => keys && week < last && onStep(week + 1),
  );

  return (
    <div className="flex items-center gap-1" role="group" aria-label={Word}>
      <IconButton
        label={`${Word} ${week - 1}`}
        icon={<ChevronLeft />}
        onClick={() => onStep(week - 1)}
        disabled={week <= first}
      />
      {/* The week and where it stands, stacked in a column of fixed width, so
          the arrows stay put whichever week is shown and whatever is said under it. */}
      <div className="flex w-28 flex-col items-center gap-0.5">
        <span className="font-mono text-[12px] tabular-nums" aria-live="polite">
          {Word} {week}
        </span>
        {/* Said, not only implied by the controls: which week this is relative to now. */}
        {week === current ? (
          <Badge variant="muted" appearance="label" className="h-4 px-1.5 text-[10.5px]">
            this {word}
          </Badge>
        ) : (
          <Button
            variant="ghost"
            aria-label={`Back to this ${word} (${word} ${current})`}
            onClick={() => onStep(current)}
            className="h-4 gap-1 px-1.5 font-mono text-[10.5px] text-muted-foreground"
          >
            <Undo2 className="size-2.5" />
            {word} {current}
          </Button>
        )}
      </div>
      <IconButton
        label={`${Word} ${week + 1}`}
        icon={<ChevronRight />}
        onClick={() => onStep(week + 1)}
        disabled={week >= last}
      />
    </div>
  );
}

/**
 * A week's content, coming in from the side it was stepped toward: the next
 * week from the right, the last from the left, the way the arrows point.
 *
 * `pending` while the week asked for is still loading and the last one is
 * held on screen: the content changes when the new week's arrives, not before,
 * so it moves once. Where there is no direction — the first week shown — it
 * only fades in, over the placeholder it replaces.
 */
export function WeekPane({
  week,
  pending = false,
  className,
  children,
  ...rest
}: {
  week: number;
  pending?: boolean;
  className?: string;
  children: React.ReactNode;
} & Partial<ReturnType<typeof useSwipe>>) {
  // The previous week, kept in state and compared during render: React's way
  // to derive from a change without an effect painting the old frame first.
  const [seen, setSeen] = useState({ week, direction: 0 });

  if (!pending && seen.week !== week) setSeen({ week, direction: Math.sign(week - seen.week) });

  return (
    <m.div
      key={seen.week}
      custom={seen.direction}
      variants={stepped}
      initial="hidden"
      animate="shown"
      className={className}
      {...rest}
    >
      {children}
    </m.div>
  );
}

/** Whether a key press belongs to something being typed into, which an arrow key must stay with. */
function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;

  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

export function useArrowKeys(onLeft: () => void, onRight: () => void) {
  // Read through a ref so the listener is attached once, not on every week.
  const handlers = useRef({ onLeft, onRight });

  useEffect(() => {
    handlers.current = { onLeft, onRight };
  });

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
