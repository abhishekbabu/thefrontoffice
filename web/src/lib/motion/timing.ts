/**
 * The app's motion vocabulary: how long motion takes and how far it travels,
 * which every other module in `lib/motion/` is built from.
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
import type { Transition } from "motion/react";

/** The default: fast enough to feel immediate, eased so it does not snap. */
export const quick: Transition = { duration: 0.18, ease: [0.22, 1, 0.36, 1] };

/** For something entering from off-screen, where a little more travel reads better. */
export const glide: Transition = { duration: 0.26, ease: [0.22, 1, 0.36, 1] };

/**
 * A spring with no overshoot, for something travelling a long way: a drawer
 * crossing the screen. Critically damped, so it settles rather than bounces —
 * a bounce on a panel the width of a table is the page wobbling.
 */
export const settle: Transition = { type: "spring", visualDuration: 0.24, bounce: 0 };

/** For a choice's marker moving between options: quick, with the faintest give at the end. */
export const slide: Transition = { type: "spring", visualDuration: 0.22, bounce: 0.1 };

/** How far content shifts sideways when its neighbour replaces it: a week stepped, a drawer swapped. */
export const STEP = 16;
