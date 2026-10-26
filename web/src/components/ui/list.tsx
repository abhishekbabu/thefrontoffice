import { m } from "motion/react";
import { Card, CardHeader } from "@/components/ui/card";
import { ErrorNote } from "@/components/ui/error-note";
import { Loading } from "@/components/ui/state";
import { list, listItem } from "@/lib/motion";
import { cn } from "@/lib/utils";

/**
 * A titled card of rows: the shape of every list the app shows inside a card.
 *
 * It was written out per panel — the league's five lists, the weeks ahead,
 * the trades, the swaps — and each copy carried the same class strings, so
 * changing the look of a row meant finding all of them. A card that fetches
 * on its own passes `loading` and `error`, and waits the same way as every
 * other: its header at once, a placeholder inside it, so the page does not
 * jump when it arrives.
 */
export function ListCard({
  title,
  count,
  aside,
  loading,
  error,
  children,
}: {
  title: string;
  /** What the card holds, said in the header's right-hand corner: "3 found", "16 weeks". */
  count?: string;
  /** Anything else for that corner, in place of `count`: a control, a status. */
  aside?: React.ReactNode;
  loading?: boolean;
  error?: Error | null;
  children?: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <span>{title}</span>
        {aside ?? (count && <span>{count}</span>)}
      </CardHeader>
      {loading && <Loading lines={2} />}
      {error && <ErrorNote error={error} />}
      {!loading && !error && (
        <m.div variants={list} initial="hidden" animate="shown" className="flex flex-col">
          {children}
        </m.div>
      )}
    </Card>
  );
}

/**
 * One row of a list card, with the one that is yours marked.
 *
 * A tint alone will not do it: `muted` is a hair off the card in light mode,
 * and a reader who cannot see the hue gets no marker at all. The rule here is
 * the same as everywhere else in this app — state carried in color is also
 * carried in shape, so the row keeps a solid rule down its left edge.
 */
export function ListRow({
  children,
  current,
  className,
  onClick,
}: {
  children: React.ReactNode;
  current?: boolean;
  className?: string;
  onClick?: () => void;
}) {
  return (
    <m.div
      variants={listItem}
      onClick={onClick}
      onKeyDown={onClick && ((e) => e.key === "Enter" && onClick())}
      tabIndex={onClick ? 0 : undefined}
      role={onClick ? "button" : undefined}
      className={cn(
        "flex items-baseline gap-3 border-t border-border py-2.5 pr-4 text-[13px] first:border-t-0",
        current ? "border-l-2 border-l-foreground bg-muted pl-[calc(1rem-2px)]" : "pl-4",
        onClick && "cursor-pointer hover:bg-muted",
        className,
      )}
    >
      {children}
    </m.div>
  );
}
