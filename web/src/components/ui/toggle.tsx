import { createContext, useContext, useId } from "react";
import { m } from "motion/react";
import { pressable, slide } from "@/lib/motion";
import { cn } from "@/lib/utils";

/** The group a chip belongs to, where only one of them is chosen at a time: its marker's shared name. */
const Group = createContext<string | null>(null);

/**
 * Chips of which exactly one is chosen — a team, a palette, a setting's value —
 * whose fill slides from the old choice to the new rather than blinking out
 * on one and in on the other. Adds no element: the chips stay laid out by
 * whatever holds them.
 */
export function ToggleGroup({ children }: { children: React.ReactNode }) {
  return <Group.Provider value={useId()}>{children}</Group.Provider>;
}

/**
 * One choice of several, pressed or not: a position filter, a team, a palette.
 *
 * Three groups had three looks for "this one is chosen" — a fill, an outline,
 * a tint — which read as three kinds of control. One fill now, because it is
 * the one that holds up for a reader who cannot see the hue: the chosen chip
 * changes its ground and its text, not only its colour. Tabs are not this:
 * they change what the page shows, and stay quieter.
 *
 * The border is kept, transparent, on the chosen chip: without it a chip is
 * two pixels narrower pressed than not, and the row shifts under the click.
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
  const group = useContext(Group);
  return (
    <button
      onClick={onClick}
      aria-pressed={pressed}
      className={cn(
        "relative isolate flex h-9 items-center gap-2 rounded-md border px-3 text-[13px]",
        pressable,
        pressed ? "border-transparent text-primary-foreground" : "border-border hover:bg-muted",
        pressed && !group && "bg-primary",
        className,
      )}
    >
      {pressed && group && (
        <m.span
          aria-hidden
          layoutId={`${group}-chip`}
          transition={slide}
          className="absolute -inset-px -z-10 rounded-md bg-primary"
        />
      )}
      {children}
    </button>
  );
}
