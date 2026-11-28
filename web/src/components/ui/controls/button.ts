import type { Html } from "@effect/ui/html";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { pressable } from "@/lib/motion/press";

export const buttonVariants = cva(
  `inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ${pressable} disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0`,
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-foreground hover:opacity-90",
        secondary: "bg-secondary text-secondary-foreground hover:bg-accent",
        ghost: "text-muted-foreground hover:bg-muted hover:text-foreground",
        outline: "border border-border bg-transparent hover:bg-muted",
      },
      size: { sm: "h-7 px-2.5 text-[13px]", md: "h-9 px-4", icon: "size-8" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export type ButtonVariants = VariantProps<typeof buttonVariants>;

/**
 * The app's button, in one of its looks.
 *
 * A key pressed on it is its own: it holds a `keydown` of its own, so a row
 * that opens on Enter (`lib/clickable.ts`) never hears the Enter that pressed
 * a button inside it. The browser still turns that Enter into the click.
 */
export function Button<M>(h: Html.H<M>, { variant, size, class: extra }: ButtonVariants & { class?: string | undefined } = {}) {
  return h.button
    .attrs({ type: "button", class: cn(buttonVariants({ variant, size }), extra) })
    .on("keydown", () => undefined);
}
