import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type * as React from "react";
import { AnimatePresence, m, useIsPresent } from "motion/react";
import { backdrop, slideOver, type Swap } from "@/lib/motion";
import { ChevronLeft, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { IconButton } from "@/components/ui/icon-button";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select, [tabindex]:not([tabindex="-1"])';

/**
 * A panel over the page from its right edge, which the rest of the page waits behind.
 *
 * A dialog in every sense a reader can tell: announced as one and as modal,
 * focus moved into it on open and kept there, Escape and a click on the
 * backdrop both close it, and focus goes back to whatever opened it — so a
 * keyboard user lands on the row they came from rather than at the top of
 * the page.
 *
 * Mounted whether or not it is open — `open` false is the closed state, not a
 * reason to render nothing. A caller that instead dropped the component would
 * take this AnimatePresence down with it, and an exit animation cannot play
 * from a tree that has already gone.
 */
export function SlideOver({
  open,
  onClose,
  label,
  className,
  children,
}: {
  open: boolean;
  onClose: () => void;
  /** The dialog's accessible name: what it is about. */
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  // Portalled to the body: a page panel animates in with a transform, and a
  // transformed ancestor makes `position: fixed` measure from it rather than
  // the viewport, so the drawer would stop at the page's width cap.
  return createPortal(
    <AnimatePresence>
      {open && (
        <Panel key="slide-over" label={label} onClose={onClose} className={className}>
          {children}
        </Panel>
      )}
    </AnimatePresence>,
    document.body,
  );
}

/**
 * When a Back link was last followed: the drawer that closes and the one that
 * reopens read it within a frame of the click, to swap the way Back goes.
 */
let backAt = Number.NEGATIVE_INFINITY;

/**
 * Whether the drawer `self` is replacing another, or being replaced by one,
 * and which way. On arrival `self` is not yet on the page, so any drawer
 * there is the one it replaces; on leaving, any other is the one replacing it.
 */
function swapping(self: Element | null): Swap {
  const other = [...document.querySelectorAll("[data-drawer]")].some((drawer) => drawer !== self);
  if (!other) return null;
  return performance.now() - backAt < 300 ? "back" : "forward";
}

function Panel({
  label,
  onClose,
  className,
  children,
}: {
  label: string;
  onClose: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  const panel = useRef<HTMLElement>(null);
  // Read by the variants when they are resolved, not now: see `slideOver`.
  const swap = () => swapping(panel.current);
  // Leaving, it stops answering at once: a click meant for the drawer
  // replacing it would otherwise land on this one's backdrop and close both.
  const present = useIsPresent();

  // Mounted on open and unmounted on close, so this runs exactly once each way.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panel.current?.focus();
    return () => opener?.focus();
  }, []);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !panel.current) return;
    // Round and round inside: tabbing out of a modal lands on a page that
    // cannot be used until it closes.
    const stops = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const first = stops[0];
    const last = stops[stops.length - 1];
    if (!first || !last) {
      e.preventDefault();
    } else if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      className={cn("fixed inset-0 z-50 flex justify-end", !present && "pointer-events-none")}
      onClick={present ? onClose : undefined}
      role="presentation"
    >
      {/* Its own layer rather than the ground the panel sits on, so it can
          stay put while the panel is swapped for another. */}
      <m.div
        aria-hidden
        custom={swap}
        variants={backdrop}
        initial="hidden"
        animate="shown"
        exit="gone"
        className="absolute inset-0 bg-scrim"
      />
      <m.aside
        ref={panel}
        data-drawer
        custom={swap}
        variants={slideOver}
        initial="hidden"
        animate="shown"
        exit="gone"
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        onClick={(e) => e.stopPropagation()}
        className={cn("relative flex h-full w-full flex-col overflow-y-auto bg-popover shadow-lg outline-none", className)}
      >
        {children}
      </m.aside>
    </div>
  );
}

/**
 * A slide-over's pinned top: what it is about, a line under that, its own
 * controls, and the way out. Shared by every drawer that is not a player's.
 */
export function SlideOverHeader({
  title,
  meta,
  back,
  onClose,
  children,
}: {
  title: React.ReactNode;
  meta?: React.ReactNode;
  back?: Back;
  onClose: () => void;
  children?: React.ReactNode;
}) {
  return (
    <div className="sticky top-0 z-10 flex items-start gap-4 border-b border-border bg-popover px-5 py-4">
      <div className="min-w-0 flex-1">
        <BackLink back={back} />
        <h2 className="font-display text-[20px] font-semibold leading-tight tracking-tight">{title}</h2>
        {meta && <p className="mt-0.5 font-mono text-[12px] text-muted-foreground">{meta}</p>}
      </div>
      {children}
      <IconButton label="Close" side="left" icon={<X />} onClick={onClose} />
    </div>
  );
}

/**
 * Where a drawer was opened from, to return to. One drawer shows at a time:
 * opening a player from a move swaps the move out, and this brings it back.
 */
export type Back = { label: string; onBack: () => void };

/** "← Trade · A ↔ B": the drawer this one replaced, above its title. */
export function BackLink({ back }: { back?: Back }) {
  if (!back) return null;
  return (
    <button
      type="button"
      onClick={() => {
        backAt = performance.now();
        back.onBack();
      }}
      className="mb-1 flex max-w-full items-center gap-1 font-mono text-[11px] text-muted-foreground hover:text-foreground"
    >
      <ChevronLeft className="size-3.5 shrink-0" aria-hidden />
      <span className="truncate">{back.label}</span>
    </button>
  );
}
