import { ExternalLink as ExternalLinkIcon } from "lucide-react";
import { Tooltip } from "@/components/ui/overlays/tooltip";
import { cn } from "@/lib/utils";

/**
 * The way across to the platform this league actually lives on.
 *
 * Reading it is what this app does; the moves are made there, so every view
 * that shows a league offers the way out to it. Always a new tab — you come
 * here to decide and go there to act, and losing the page you decided from is
 * the one thing that must not happen.
 *
 * `noreferrer` alongside `noopener`: the target has no business knowing which
 * page sent you, and `noopener` alone still leaks a referrer.
 */
export function ExternalLink({
  href,
  label,
  className,
  children,
}: {
  href: string;
  label: string;
  className?: string;
  children?: React.ReactNode;
}) {
  if (!href) return null;

  return (
    <Tooltip label={label}>
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={label}
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-[13px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground motion-reduce:transition-none",
          className,
        )}
      >
        {children}
        <ExternalLinkIcon className="size-3.5 shrink-0" aria-hidden />
      </a>
    </Tooltip>
  );
}
