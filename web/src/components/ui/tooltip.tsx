import * as React from "react";
import * as RadixTooltip from "@radix-ui/react-tooltip";

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
