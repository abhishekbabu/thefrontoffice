import type { ReactNode } from "react";
import { LazyMotion, MotionConfig, type FeatureBundle, type LazyFeatureBundle } from "motion/react";

/**
 * What every animated component in the app is rendered under: the feature
 * set, and the rule that a viewer who asked their system for less motion gets
 * it, without a branch at any call site.
 *
 * `reducedMotion="user"` follows `prefers-reduced-motion`: movement — a
 * drawer crossing, a week sliding, a marker gliding between tabs — happens in
 * one frame, and only fades remain. Shared with the test renderer, so the
 * suite runs under the same rule the app does.
 *
 * `strict` makes a stray `motion.*` import — which would put the whole library
 * in the bundle that imported it — a runtime error.
 */
export function MotionProvider({
  features,
  children,
}: {
  features: FeatureBundle | LazyFeatureBundle;
  children: ReactNode;
}) {
  return (
    <LazyMotion features={features} strict>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </LazyMotion>
  );
}
