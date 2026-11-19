/**
 * The app's motion vocabulary, in one place.
 *
 * Every transition is short and every distance is small: this is a page you
 * check before a deadline, and animation that draws attention to itself is a
 * delay you notice on the second visit. Motion is loaded lazily through
 * `LazyMotion`, which keeps the initial bundle to a few kilobytes rather than
 * the thirty the full library costs.
 *
 * Everything here respects `prefers-reduced-motion` via `MotionConfig` in the
 * app shell, so a viewer who asked for stillness gets it without a branch here:
 * movement (transforms, layout) is dropped and fades remain. Press feedback,
 * hover, tooltips and the phone menu are CSS instead (`motion-safe:` and the
 * keyframes in index.css): no script, and working before this chunk arrives.
 */
import type { Transition, Variants } from "motion/react";

/**
 * A control giving a little under the pointer, and its hover easing in.
 *
 * CSS rather than `whileTap`: it answers on the press itself, needs none of
 * the lazily loaded features, and costs nothing per control. `motion-safe:`
 * keeps the scale from anyone who asked for stillness; the color still eases.
 */
export const pressable = "transition duration-150 ease-out motion-safe:active:scale-[0.97]";

/**
 * The same for a row. A scale on something the width of the page reads as the
 * page moving, so its ground goes a shade darker under the press instead.
 */
export const pressableRow = "transition-colors duration-150 ease-out active:bg-secondary";

/** The default: fast enough to feel immediate, eased so it does not snap. */
export const quick: Transition = { duration: 0.18, ease: [0.22, 1, 0.36, 1] };

/** For something entering from off-screen, where a little more travel reads better. */
export const glide: Transition = { duration: 0.26, ease: [0.22, 1, 0.36, 1] };

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
 * A spring with no overshoot, for something travelling a long way: a drawer
 * crossing the screen. Critically damped, so it settles rather than bounces —
 * a bounce on a panel the width of a table is the page wobbling.
 */
export const settle: Transition = { type: "spring", visualDuration: 0.24, bounce: 0 };

/** For a choice's marker moving between options: quick, with the faintest give at the end. */
export const slide: Transition = { type: "spring", visualDuration: 0.22, bounce: 0.1 };

/** How far content shifts sideways when its neighbour replaces it: a week stepped, a drawer swapped. */
const STEP = 16;

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

/**
 * A list revealing itself.
 *
 * The delay is deliberately tiny: a fifteen-row lineup at 40ms a row takes
 * most of a second to finish, which is a page that feels slow rather than
 * alive. `staggerChildren` also caps the total, so long lists do not grow
 * unboundedly slower.
 */
export const list: Variants = {
  hidden: {},
  shown: { transition: { staggerChildren: 0.012, delayChildren: 0.02 } },
};

export const listItem: Variants = {
  hidden: { opacity: 0, y: 4 },
  shown: { opacity: 1, y: 0, transition: quick },
};

/**
 * A portrait arriving after the name beside it.
 *
 * Opens its own room rather than appearing in it: the width grows from nothing
 * and the negative margin cancels the row's gap until it does, so the name
 * slides over once instead of jumping. 96px and the 16px gap are the drawer's.
 */
export const portrait: Variants = {
  hidden: { opacity: 0, width: 0, marginRight: -16 },
  shown: { opacity: 1, width: 96, marginRight: 0, transition: glide },
};
