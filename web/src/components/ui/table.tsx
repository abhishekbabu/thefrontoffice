import * as React from "react";
import { cn } from "@/lib/utils";

/** Wide tables scroll inside themselves; the page never scrolls sideways. */
function Table({ className, ...props }: React.ComponentProps<"table">) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full border-collapse text-[13px]", className)} {...props} />
    </div>
  );
}

function Th({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      className={cn(
        "whitespace-nowrap border-b border-border px-4 py-2 text-left",
        "font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

function Td({ className, ...props }: React.ComponentProps<"td">) {
  return <td className={cn("border-b border-border/45 px-4 py-2 tabular-nums", className)} {...props} />;
}

export { Table, Th, Td };
