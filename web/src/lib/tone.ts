import type { Stat, TaskVerdict } from "@/lib/api";

/** The badge's vocabulary: semantic, so a caller maps its own meaning onto it. */
export type Variant = "ok" | "info" | "warn" | "fail" | "muted";

/** Agreeing costs nothing to act on; an overrule is the one to stop and read. */
export const decisionTone = (decision: TaskVerdict["decision"]): Variant =>
  decision === "AGREE" ? "ok" : decision === "OVERRULE" ? "fail" : "warn";

/**
 * The text color a server's tone asks for.
 *
 * `neutral` takes whatever the caller's quiet color is — muted in a list of
 * figures, the body color where the figure is the point.
 */
export function toneText(tone: Stat["tone"], neutral = ""): string {
  return tone === "good" ? "text-ok" : tone === "warning" ? "text-warn" : neutral;
}
