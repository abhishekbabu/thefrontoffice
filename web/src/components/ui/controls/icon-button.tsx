import * as React from "react";
import { Tooltip } from "@/components/ui/overlays/tooltip";
import { Button, type buttonVariants } from "@/components/ui/controls/button";
import type { VariantProps } from "class-variance-authority";

/**
 * An icon control that always carries its name.
 *
 * The label is required, not optional: an icon alone is a guess, and the two
 * places it has to appear — a tooltip for a mouse, an accessible name for a
 * screen reader and for keyboard focus — are the same string. Taking one
 * argument makes it impossible to supply one and forget the other.
 */
export function IconButton({
  label,
  icon,
  side,
  ...props
}: {
  label: string;
  icon: React.ReactNode;
  side?: "top" | "right" | "bottom" | "left";
} & React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants>) {
  return (
    <Tooltip label={label} side={side}>
      <Button size="icon" variant="ghost" aria-label={label} {...props}>
        {icon}
      </Button>
    </Tooltip>
  );
}
