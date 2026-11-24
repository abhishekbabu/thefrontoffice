import { useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Undo2 } from "lucide-react";
import type { Summary } from "@/lib/types";
import { addDays, dayLabel, isDay } from "@/lib/days";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Button } from "@/components/ui/controls/button";
import { Badge } from "@/components/ui/badge";
import { useArrowKeys } from "@/components/league/week-stepper";

/** Which day of a week a day's summary shows, and the week's days to page through. */
type DayRange = NonNullable<Summary["days"]>;

/**
 * Paging through a week a day at a time, where a lineup is set day by day: a
 * step either way inside the week, and the way back to today while the week
 * holds it. The arrow keys do the same. Each control names the day it goes to.
 */
export function DayStepper({ range, onStep }: { range: DayRange; onStep: (day: string) => void }) {
  const { day, first, last, today } = range;
  const before = addDays(day, -1);
  const after = addDays(day, 1);

  useArrowKeys(
    () => day > first && onStep(before),
    () => day < last && onStep(after),
  );

  return (
    <div className="flex items-center gap-1" role="group" aria-label="Day">
      <IconButton label={dayLabel(before)} icon={<ChevronLeft />} onClick={() => onStep(before)} disabled={day <= first} />
      {/* Fixed width, as the week's: the arrows stay put whichever day is shown. */}
      <div className="flex w-28 flex-col items-center gap-0.5">
        <span className="font-mono text-[12px] tabular-nums" aria-live="polite">
          {dayLabel(day)}
        </span>
        {today === day ? (
          <Badge variant="muted" appearance="label" className="h-4 px-1.5 text-[10.5px]">
            today
          </Badge>
        ) : today ? (
          <Button
            variant="ghost"
            aria-label={`Back to today (${dayLabel(today)})`}
            onClick={() => onStep(today)}
            className="h-4 gap-1 px-1.5 font-mono text-[10.5px] text-muted-foreground"
          >
            <Undo2 className="size-2.5" />
            today
          </Button>
        ) : (
          // A week without today has no way back to it: the line stays, so the label does not jump.
          <span aria-hidden className="h-4" />
        )}
      </div>
      <IconButton label={dayLabel(after)} icon={<ChevronRight />} onClick={() => onStep(after)} disabled={day >= last} />
    </div>
  );
}

/**
 * Which day of the shown week a page opens, named in its address as `?day=2026-11-24` beside `?week=`.
 *
 * Left off for the day a week opens on — today in the week being played, else
 * its first, as the `range` stepped within says — so that address stays the
 * week's own. Stepping keeps the week and pushes a history entry; stepping the
 * week drops the day, and the next week opens on its own.
 */
export function useDayParam() {
  const [params, setParams] = useSearchParams();
  const asked = params.get("day");
  const day = isDay(asked) ? asked : null;

  const step = (to: string, range: DayRange) =>
    setParams((now) => {
      const next = new URLSearchParams(now);

      if (to === (range.today ?? range.first)) next.delete("day");
      else next.set("day", to);

      return next;
    });

  return { day, step };
}
