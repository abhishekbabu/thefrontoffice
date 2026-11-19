import * as React from "react";
import * as RadixTooltip from "@radix-ui/react-tooltip";
import { cn } from "@/lib/utils";

/**
 * Tooltips, wrapped once so no caller assembles four Radix parts by hand.
 *
 * Radix rather than a `title` attribute because a native tooltip is invisible
 * to keyboard focus, cannot be styled, and waits a second before appearing —
 * which for a control whose label lives in the tooltip is a control with no
 * label at all.
 */
export function TooltipProvider({ children }: { children: React.ReactNode }) {
  return (
    <RadixTooltip.Provider delayDuration={250} skipDelayDuration={400}>
      {children}
    </RadixTooltip.Provider>
  );
}

export function Tooltip({
  label,
  side = "bottom",
  children,
}: {
  label: React.ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  children: React.ReactNode;
}) {
  if (!label) return <>{children}</>;
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={6}
          className="z-50 max-w-xs rounded-md border border-border bg-popover px-2.5 py-1.5 text-[12.5px] leading-snug text-popover-foreground shadow-md"
        >
          {label}
          <RadixTooltip.Arrow className="fill-border" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}

/**
 * Something on the page that explains itself on hover and on focus: an
 * abbreviated status, a name whose pricing is off his projection, a record
 * that is not the one held that week.
 *
 * Four places wrapped a span by hand for this, and one forgot the accessible
 * name. Focusable, because a note a keyboard cannot reach is a note only a
 * mouse gets; `name` is what a screen reader hears — the text and its note
 * together. `dotted` underlines plain text so it reads as having more to say;
 * a badge already looks like it does.
 */
export function Hint({
  label,
  name,
  dotted = false,
  side,
  className,
  children,
}: {
  label: React.ReactNode;
  name?: string;
  dotted?: boolean;
  side?: "top" | "right" | "bottom" | "left";
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Tooltip label={label} side={side}>
      <span
        tabIndex={0}
        aria-label={name}
        className={cn(dotted && "underline decoration-dotted underline-offset-2", className)}
      >
        {children}
      </span>
    </Tooltip>
  );
}
