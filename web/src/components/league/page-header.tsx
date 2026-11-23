import type { League } from "@/lib/api";
import { ExternalLink } from "@/components/ui/external-link";

/**
 * The bar that says where you are and what you can do from here.
 *
 * Pinned, because both halves stay relevant the whole way down a page: on a
 * long one the title is what a figure belongs to, and the controls are the way
 * out. Opaque rather than translucent — content scrolling visibly underneath
 * a title reads as two pages at once.
 *
 * `leading` sits before the title, which is where a control that leaves the
 * page belongs: back is upstream of where you are, and reads that way to the
 * left of the name of it.
 */
export function PageHeader({
  title,
  meta,
  leading,
  href,
  hrefLabel,
  children,
}: {
  title: string;
  meta?: string;
  leading?: React.ReactNode;
  /** The platform this thing lives on, opened in a new tab. */
  href?: string;
  hrefLabel?: string;
  children?: React.ReactNode;
}) {
  return (
    // The bar spans the column; what is in it keeps to the page's width
    // (`--page-max`), so the controls sit over the content they act on rather
    // than at the far edge of a wide screen.
    <header
      data-bleed
      className="sticky top-0 z-20 border-b border-border bg-background"
    >
      <div className="flex mx-auto max-w-(--page-max) flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          {leading}
          <div className="min-w-0">
            {/* On the name's own line rather than after the block: the meta line
                is much the longer of the two, so a link placed after both drifts
                out to the far right and stops reading as belonging to the name. */}
            <div className="flex min-w-0 items-center gap-1">
              <h1 className="truncate font-display text-[21px] font-semibold leading-tight tracking-tight">
                {title}
              </h1>
              {href && (
                <ExternalLink
                  href={href}
                  label={hrefLabel ?? "Open on the platform"}
                  className="h-6 shrink-0 px-1"
                />
              )}
            </div>
            {meta && (
              <p className="mt-0.5 font-mono text-[12px] text-muted-foreground">
                {meta}
              </p>
            )}
          </div>
        </div>
        {children}
      </div>
    </header>
  );
}

/**
 * The header for a page about a league, which is most of them.
 *
 * Four panels set the same four props, and each spelled the link's label out
 * again — so the one sentence a screen reader hears for "open this on the
 * platform" lived in four places and could drift in any of them. `meta`
 * defaults to the league's own detail line, which is what three of the four
 * wanted; the week overrides it to lead with the window.
 */
export function LeagueHeader({
  league,
  meta,
  children,
}: {
  league: League;
  meta?: string;
  children?: React.ReactNode;
}) {
  return (
    <PageHeader
      title={league.name}
      meta={meta ?? league.detail}
      href={league.url}
      hrefLabel={`Open ${league.name} on the platform`}
    >
      {children}
    </PageHeader>
  );
}
