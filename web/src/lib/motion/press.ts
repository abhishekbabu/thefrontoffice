/**
 * Press feedback: a control or row answering the pointer, in CSS so it works before Motion loads.
 *
 * Part of the app's motion vocabulary; see `lib/motion/timing.ts` for what it shares.
 */

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
