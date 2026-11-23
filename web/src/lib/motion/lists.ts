/**
 * Lists revealing their rows, and a portrait opening its room beside a name.
 *
 * Part of the app's motion vocabulary; see `lib/motion/timing.ts` for what it shares.
 */
import type { Variants } from "motion/react";
import { quick, glide } from "@/lib/motion/timing";

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
 * slides over once instead of jumping. It grows to the photo's own width, so a
 * smaller one leaves no blank beside it; the 16px gap is the drawer's.
 */
export const portrait: Variants = {
  hidden: { opacity: 0, width: 0, marginRight: -16 },
  shown: { opacity: 1, width: "auto", marginRight: 0, transition: glide },
};
