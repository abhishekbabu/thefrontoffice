/**
 * The animation feature set, in its own module so it can be split out.
 *
 * `LazyMotion` only defers what a dynamic import can reach, and an import of
 * `motion/react` from inside the app's entry module resolves to that same
 * bundle — so the split never happens and the whole library lands in the entry
 * chunk. Pointing the import at this file gives the bundler something separable.
 *
 * `domMax` rather than `domAnimation`: it adds layout animation, which is what
 * slides a tab's or a chip's marker to the one chosen (`layoutId`) and moves a
 * to-do row to its new place when the list reorders. It arrives after first
 * paint like the rest, so it costs the deferred chunk, not the wait for a page.
 */
export { domMax as default } from "motion/react";
