import { cn } from "@/lib/utils";

/**
 * A row of tabs: which part of a page is shown.
 *
 * Quieter than a `ToggleChip`, which filters what a list holds; a tab changes
 * what the page shows.
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
  return (
    <div className={cn("flex items-center gap-1 overflow-x-auto", className)} role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={t.id === current}
          onClick={() => onPick(t.id)}
          className={cn(
            "shrink-0 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors",
            t.id === current ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-muted",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
