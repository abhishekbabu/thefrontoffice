import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

/**
 * Something kept out of the way under a labelled row that opens it: the to-do
 * items put aside, the steps for reading Yahoo without its API.
 *
 * A native `<details>`, so it opens by keyboard and is found by the browser's
 * own search with nothing to wire. Its summary is a label, ruled off from
 * whatever sits above it in the card.
 */
export function Disclosure({
  summary,
  open,
  className,
  children,
}: {
  summary: React.ReactNode;
  /** Open on arrival: where what it holds is what is needed now. */
  open?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <details open={open} className={cn("border-t border-border", className)}>
      <Label as="summary" className="cursor-pointer px-4 py-2.5 hover:text-foreground">
        {summary}
      </Label>
      {children}
    </details>
  );
}
