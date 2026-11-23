import { useId } from "react";
import { m } from "motion/react";
import { pressable } from "@/lib/motion/press";
import { slide } from "@/lib/motion/timing";
import { cn } from "@/lib/utils";

/**
 * A row of tabs: which part of a page is shown.
 *
 * Quieter than a `ToggleChip`, which filters what a list holds; a tab changes
 * what the page shows. The chosen tab's ground slides to the next one picked,
 * so the eye follows the choice rather than finding it again.
 */
export function Tabs<T extends string>({
  tabs,
  current,
  onPick,
  className,
}: {
  tabs: { id: T; label: string }[];
  current: T | undefined;
  onPick: (id: T) => void;
  className?: string;
}) {
  // One marker per row of tabs: two rows on a page must not trade theirs.
  const marker = `${useId()}-tab`;

  return (
    <div className={cn("flex items-center gap-1 overflow-x-auto", className)} role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={t.id === current}
          onClick={() => onPick(t.id)}
          className={cn(
            "relative isolate shrink-0 rounded-md px-3 py-1.5 text-[13px] font-medium",
            pressable,
            t.id === current ? "text-foreground" : "text-muted-foreground hover:bg-muted",
          )}
        >
          {t.id === current && (
            <m.span
              aria-hidden
              layoutId={marker}
              transition={slide}
              className="absolute inset-0 -z-10 rounded-md bg-secondary"
            />
          )}
          {t.label}
        </button>
      ))}
    </div>
  );
}
