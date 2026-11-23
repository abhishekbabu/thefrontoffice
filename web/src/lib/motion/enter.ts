/**
 * Content arriving and leaving in place: a panel rising in, a week stepped, a row collapsing, a docked panel opening.
 *
 * Part of the app's motion vocabulary; see `lib/motion/timing.ts` for what it shares.
 */
import type { Variants } from "motion/react";
import { quick, STEP } from "@/lib/motion/timing";

/**
 * A panel arriving: content shifting up a few pixels as it fades in.
 *
 * Leaves downward, back the way it came, so a page swapped under `mode="wait"`
 * reads as one movement rather than two unrelated ones. Faster out than in —
 * the thing you are leaving has already been read.
 */
export const rise: Variants = {
  hidden: { opacity: 0, y: 6 },
  shown: { opacity: 1, y: 0, transition: quick },
  gone: { opacity: 0, y: 6, transition: { duration: 0.12, ease: [0.22, 1, 0.36, 1] } },
};

/**
 * One week's content replacing another's: in from the side it was stepped
 * toward (the next week from the right, the last from the left) and only
 * faded in where there is no direction, as when a week first arrives.
 * No exit: the old week is already read, and holding it back would hold back
 * the new one.
 */
export const stepped: Variants = {
  hidden: (direction: number) => ({ opacity: 0, x: direction * STEP }),
  shown: { opacity: 1, x: 0, transition: quick },
};

/**
 * A row closing up as it leaves a list and opening as it joins one: a to-do
 * item dismissed, snoozed or restored. The rows below follow it rather than
 * jumping, with nothing to measure.
 */
export const collapse: Variants = {
  // Clipped only while it moves: a row left clipped would cut off the focus
  // ring of whatever inside it sits against its edge.
  hidden: { opacity: 0, height: 0, overflow: "hidden" },
  shown: { opacity: 1, height: "auto", transition: quick, transitionEnd: { overflow: "visible" } },
  gone: { opacity: 0, height: 0, overflow: "hidden", transition: { duration: 0.16, ease: [0.22, 1, 0.36, 1] } },
};

/**
 * A panel docked in a corner, opening out of the button that stands for it.
 *
 * Hidden rather than unmounted: what it holds — a conversation half read —
 * should be exactly where it was when it opens again.
 */
export const dock: Variants = {
  hidden: { opacity: 0, y: 12, scale: 0.98, transition: { duration: 0.12 }, transitionEnd: { display: "none" } },
  shown: { display: "flex", opacity: 1, y: 0, scale: 1, transition: quick },
};

export const fade: Variants = {
  hidden: { opacity: 0 },
  shown: { opacity: 1, transition: quick },
  gone: { opacity: 0, transition: { duration: 0.12 } },
};
