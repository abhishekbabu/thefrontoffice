import { cn } from "@/lib/utils";

/**
 * One choice of several, pressed or not: a position filter, a team, a palette.
 *
 * Three groups had three looks for "this one is chosen" — a fill, an outline,
 * a tint — which read as three kinds of control. One fill now, because it is
 * the one that holds up for a reader who cannot see the hue: the chosen chip
 * changes its ground and its text, not only its colour. Tabs are not this:
 * they change what the page shows, and stay quieter.
 */
export function ToggleChip({
  pressed,
  onClick,
  className,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={pressed}
      className={cn(
        "flex h-9 items-center gap-2 rounded-md px-3 text-[13px] transition-colors",
        pressed ? "bg-primary text-primary-foreground" : "border border-border hover:bg-muted",
        className,
      )}
    >
      {children}
    </button>
  );
}
