/**
 * Drawers: a slide-over arriving, leaving, or swapping in place for another, and the page dimmed behind it.
 *
 * Part of the app's motion vocabulary; see `lib/motion/timing.ts` for what it shares.
 */
import type { Transition, Variants } from "motion/react";
import { quick, settle, STEP } from "@/lib/motion/timing";

/**
 * How a drawer arrives and leaves relative to another one.
 *
 * `null` when it is the only one: it crosses from the screen's edge. When it
 * replaces another (a player opened from a move, and Back to the move), the
 * page behind has not changed, so it should not dim and lighten again: the new
 * drawer fades in a step to the side, `forward` from the right and `back` from
 * the left, and the one it replaced fades the other way.
 */
export type Swap = "forward" | "back" | null;

/**
 * A drawer leaving across the screen: gathering speed as it goes. The
 * arriving ease front-loads the move, which out of a resting drawer put 40%
 * of the screen into the first frame and read as a jump.
 */
const leave: Transition = { duration: 0.2, ease: [0.4, 0, 0.7, 0.2] };

/**
 * A slide-over from the right, or a swap in place where it replaces another.
 *
 * Each variant takes a function rather than a value, because whether this is
 * a swap is only known when the variant is read: on arrival, whether another
 * drawer is still on screen; on leaving, whether one has just taken its place.
 */
export const slideOver: Variants = {
  hidden: (swap: () => Swap) => {
    const s = swap();

    return s ? { opacity: 0, x: s === "back" ? -STEP : STEP } : { opacity: 1, x: "100%" };
  },
  // A swap travels a step, not the screen: the quick ease, not the spring's tail.
  shown: (swap: () => Swap) => ({ opacity: 1, x: 0, transition: swap() ? quick : settle }),
  gone: (swap: () => Swap) => {
    const s = swap();

    return s
      ? { opacity: 0, x: s === "back" ? STEP : -STEP, transition: { duration: 0.14, ease: [0.22, 1, 0.36, 1] } }
      : { x: "100%", transition: leave };
  },
};

/**
 * The dimmed page behind a drawer. Already there when a drawer replaces
 * another, and gone at once from the one it replaced, so the page keeps one
 * shade throughout instead of two layers of it crossing.
 */
export const backdrop: Variants = {
  hidden: (swap: () => Swap) => ({ opacity: swap() ? 1 : 0 }),
  shown: { opacity: 1, transition: quick },
  gone: (swap: () => Swap) => ({ opacity: 0, transition: swap() ? { duration: 0 } : { duration: 0.18 } }),
};
