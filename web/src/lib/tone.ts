import type { MoveAction, TaskVerdict, TradeVerdict } from "@/lib/api";

export type Tone = "ok" | "info" | "warn" | "fail" | "muted";

/**
 * Map a recommendation onto the shared status vocabulary.
 *
 * Grouped by what a move costs rather than by what it is called: the free ones
 * that only rearrange what you already own read as `info`, the ones that spend
 * a transfer or a roster spot read as `warn`, and the single highest-leverage
 * decision of a week gets `ok` so it is never lost among them.
 */
const MOVE_TONES: Record<MoveAction, Tone> = {
  CAPTAIN: "ok",
  START: "info",
  BENCH: "info",
  ADD: "warn",
  TRANSFER: "warn",
  DROP: "fail",
  MONITOR: "muted",
};

export const moveTone = (action: MoveAction): Tone => MOVE_TONES[action] ?? "muted";

export const verdictTone = (verdict: TradeVerdict["verdict"]): Tone =>
  verdict === "ACCEPT" ? "ok" : verdict === "REJECT" ? "fail" : "warn";

/** Agreeing costs nothing to act on; an overrule is the one to stop and read. */
export const decisionTone = (decision: TaskVerdict["decision"]): Tone =>
  decision === "AGREE" ? "ok" : decision === "OVERRULE" ? "fail" : "warn";
