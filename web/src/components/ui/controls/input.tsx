import * as React from "react";
import { Search } from "lucide-react";
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

const FIELD =
  "h-9 w-full min-w-0 rounded-md border border-input bg-background px-3 text-[13px] placeholder:text-muted-foreground focus-visible:border-ring disabled:opacity-50";

/**
 * A text field with a magnifier in it: the wire's search, the compare finder.
 *
 * Written twice with the icon placed by hand, and the two placements differed
 * by the padding of whatever each sat in. Placed against the field here, so it
 * lands in the same spot wherever the field goes.
 */
function SearchInput({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <div className={cn("relative min-w-0", className)}>
      <Search
        className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
      <Input className="pl-8" {...props} />
    </div>
  );
}

export { Input, SearchInput };
