import type { TaskVerdict } from "@/lib/api";

export type Tone = "ok" | "info" | "warn" | "fail" | "muted";

/** Agreeing costs nothing to act on; an overrule is the one to stop and read. */
export const decisionTone = (decision: TaskVerdict["decision"]): Tone =>
  decision === "AGREE" ? "ok" : decision === "OVERRULE" ? "fail" : "warn";
