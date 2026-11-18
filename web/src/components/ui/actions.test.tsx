import { describe, expect, it } from "vitest";
import type { Action, TaskVerdict } from "@/lib/api";
import { ActionList, staleVerdicts } from "@/components/ui/actions";
import { render } from "@/test/render";

function action(key: string, verdict: TaskVerdict | null = null, stale = false): Action {
  return {
    kind: "waiver",
    urgency: "soon",
    key,
    title: `Pick up ${key}`,
    reason: "Projects 7.56, best DEF available.",
    when: "",
    player_id: "",
    replaces: "",
    drop: "",
    win_change: null,
    evidence: [],
    verdict,
    stale,
    mark: { hidden: null, snoozed_until: null, resurfaced: false },
    chance: null,
    fingerprint: key,
  };
}

const said = (decision: TaskVerdict["decision"], reason: string): TaskVerdict => ({ task: "T1", decision, reason });

describe("ActionList verdicts", () => {
  it("shows an agreement as a chip alone, without the model's sentence", async () => {
    const { container } = await render(
      <ActionList actions={[action("lions", said("AGREE", "Lions give 7.56 pts vs zero from Packers"))]} />,
    );

    expect(container.textContent).toContain("Agree");
    expect(container.textContent).not.toContain("zero from Packers");
  });

  it("shows the reason where the model overrules or waits", async () => {
    const { container } = await render(
      <ActionList
        actions={[
          action("a", said("OVERRULE", "His snaps fell to a third.")),
          action("b", said("WAIT", "Questionable; inactives Sunday.")),
        ]}
      />,
    );

    expect(container.textContent).toContain("His snaps fell to a third.");
    expect(container.textContent).toContain("Questionable; inactives Sunday.");
  });

  it("says stale on no row: the list's header says it once", async () => {
    const { container } = await render(
      <ActionList actions={[action("a", said("OVERRULE", "No."), true), action("b", said("AGREE", "Yes."), true)]} />,
    );

    expect(container.textContent?.toLowerCase()).not.toContain("stale");
  });
});

describe("staleVerdicts", () => {
  it("is true while any shown item's verdict is stale, and ignores hidden ones and items never judged", () => {
    const hidden: Action = {
      ...action("h", said("AGREE", ""), true),
      mark: { hidden: "dismissed", snoozed_until: null, resurfaced: false },
    };

    expect(staleVerdicts([action("a", said("AGREE", ""), true)])).toBe(true);
    expect(staleVerdicts([hidden, action("b", null, true), action("c", said("AGREE", ""))])).toBe(false);
  });
});
