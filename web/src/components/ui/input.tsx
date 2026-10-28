import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * A single-line text field: the chat box, the wire's search, a setting.
 *
 * Each was styled where it stood and they drifted — two borders, two heights,
 * and one that switched off the focus ring every other control keeps. The
 * ring comes from the global `:focus-visible` rule, so nothing here removes it.
 */
function Input({ className, ...props }: React.ComponentProps<"input">) {
  return <input className={cn(FIELD, className)} {...props} />;
}

/** The same field as a `<select>`, for a setting with a fixed set of values. */
function Select({ className, ...props }: React.ComponentProps<"select">) {
  return <select className={cn(FIELD, className)} {...props} />;
}

const FIELD =
  "h-9 w-full min-w-0 rounded-md border border-input bg-background px-3 text-[13px] placeholder:text-muted-foreground focus-visible:border-ring disabled:opacity-50";

export { Input, Select };
