import type { Html } from "@effect/ui/html";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * Variants are semantic, not domain-specific: callers map their own vocabulary
 * onto ok / info / warn / fail rather than the badge learning about fixtures,
 * injuries or verdicts.
 */
const badgeVariants = cva(
  "inline-flex h-5 w-fit items-center gap-1.5 whitespace-nowrap px-2.5 font-mono text-[11px] font-semibold leading-none",
  {
    variants: {
      variant: {
        ok: "bg-ok/15 text-ok",
        info: "bg-accent-foreground/15 text-accent-foreground",
        warn: "bg-warn/15 text-warn",
        fail: "bg-destructive/12 text-destructive",
        muted: "bg-muted text-muted-foreground border border-border",
      },
      appearance: {
        // The leading dot repeats the variant as a shape, so status survives
        // where the hue does not — print, low contrast, color blindness.
        status: "rounded-full before:size-1.5 before:shrink-0 before:rounded-full before:bg-current",
        pill: "rounded-full",
        label: "rounded-sm",
      },
    },
    defaultVariants: { variant: "muted", appearance: "label" },
  },
);

export type BadgeVariants = VariantProps<typeof badgeVariants>;

export function Badge<M>(
  h: Html.H<M>,
  { variant, appearance, class: extra }: BadgeVariants & { class?: string | undefined } = {},
) {
  return h.span.attr("class", cn(badgeVariants({ variant, appearance }), extra));
}
