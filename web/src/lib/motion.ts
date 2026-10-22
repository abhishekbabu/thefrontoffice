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
 * app shell, so a viewer who asked for stillness gets it without a branch here.
 */
import type { Transition, Variants } from "motion/react";

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

/** A slide-over from the right. */
export const slideOver: Variants = {
  hidden: { x: "100%" },
  shown: { x: 0, transition: glide },
  gone: { x: "100%", transition: { ...glide, duration: 0.18 } },
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
