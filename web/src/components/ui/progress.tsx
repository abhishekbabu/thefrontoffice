import { cn } from "@/lib/utils";

/**
 * A slim bar with a segment sweeping across it: work under way, of a length
 * nobody knows.
 *
 * Indeterminate on purpose. The server says nothing about how far along a
 * league's first load is, so a bar that filled would be inventing a figure;
 * a sweep says only that something is moving, which is true. It replaced
 * shimmering placeholder rows, which at a glance read as a page that had
 * loaded empty rather than one still on its way.
 *
 * The sweep is CSS (`animate-loading-bar` in index.css), so it runs before the
 * motion chunk arrives. A viewer who asked for stillness gets the segment
 * held in place, and the word beside it carries the state either way.
 */
export function LoadingBar({ label = "Loading", className }: { label?: string; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div
        role="progressbar"
        aria-label={label}
        className="relative h-1 w-full overflow-hidden rounded-full bg-secondary"
      >
        <div className="absolute inset-y-0 left-0 w-2/5 rounded-full bg-primary motion-safe:animate-loading-bar motion-reduce:left-[30%]" />
      </div>
      <span className="font-mono text-[11px] tracking-wide text-muted-foreground uppercase">{label}…</span>
    </div>
  );
}
