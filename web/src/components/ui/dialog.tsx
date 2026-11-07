import { useEffect, useRef } from "react";
import type * as React from "react";
import { AnimatePresence, m } from "motion/react";
import { fade, slideOver } from "@/lib/motion";
import { cn } from "@/lib/utils";

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
  return (
    <AnimatePresence>
      {open && (
        <m.div
          key="slide-over"
          variants={fade}
          initial="hidden"
          animate="shown"
          exit="gone"
          className="fixed inset-0 z-50 flex justify-end bg-foreground/20"
          onClick={onClose}
          role="presentation"
        >
          <Panel label={label} onClose={onClose} className={className}>
            {children}
          </Panel>
        </m.div>
      )}
    </AnimatePresence>
  );
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
    <m.aside
      ref={panel}
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
      className={cn("flex h-full w-full flex-col overflow-y-auto bg-popover shadow-lg outline-none", className)}
    >
      {children}
    </m.aside>
  );
}
