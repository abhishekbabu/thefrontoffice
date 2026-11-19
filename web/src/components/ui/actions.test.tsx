import { describe, expect, it, vi } from "vitest";
import type { Action, MovePlayer, TaskVerdict } from "@/lib/api";
import { ActionList, Compared, opener, staleVerdicts } from "@/components/ui/actions";
import { render, settle } from "@/test/render";

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
    players: [],
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

const player = (
  side: MovePlayer["side"],
  name: string,
  held: MovePlayer["held"],
  [snaps, proj, opp]: [string, string, string],
): MovePlayer => ({
  side,
  player_id: name,
  name,
  position: "WR",
  team: "TEN",
  held,
  figures: [
    { label: "Snap% (L3)", value: snaps, tone: "neutral", url: "", better: null, hint: "" },
    { label: "Proj", value: proj, tone: "neutral", url: "", better: null, hint: "" },
    { label: "Opp", value: opp, tone: "good", url: "", better: null, hint: "" },
  ],
});

describe("putting an item aside", () => {
  it("takes it out of the list and under Hidden, and back again on restore", async () => {
    const dismissed: Action = { ...action("b"), mark: { hidden: "dismissed", snoozed_until: null, resurfaced: false } };
    const { container, rerender } = await render(<ActionList actions={[action("a"), action("b")]} />);
    const listed = () => [...container.querySelectorAll("ol > li")].map((li) => li.textContent);

    await rerender(<ActionList actions={[action("a"), dismissed]} />);
    await settle();
    expect(listed()).toHaveLength(1);
    expect(listed()[0]).toContain("Pick up a");
    expect(container.textContent).toContain("Hidden (1)");

    await rerender(<ActionList actions={[action("a"), action("b")]} />);
    await settle();
    expect(listed()).toHaveLength(2);
    expect(container.textContent).not.toContain("Hidden");
  });

  it("says nothing is left once the last item is put aside", async () => {
    const dismissed: Action = { ...action("a"), mark: { hidden: "dismissed", snoozed_until: null, resurfaced: false } };
    const { container, rerender } = await render(<ActionList actions={[action("a")]} />);

    await rerender(<ActionList actions={[dismissed]} />);
    await settle();

    expect(container.querySelectorAll("ol > li")).toHaveLength(0);
    expect(container.textContent).toContain("Nothing left.");
  });
});

describe("a move between two players", () => {
  const dike = player("in", "Chimere Dike", "free agent", ["66%", "9.88", "vs DAL, 6th-easiest"]);
  const swap: Action = {
    ...action("dike"),
    players: [dike, player("out", "Antonio Williams", "bench", ["40%", "8.20", "vs KC, 2nd-toughest"])],
  };

  it("lines the two players up in columns, each figure on its own row read across", async () => {
    const { container } = await render(<ActionList actions={[swap]} />);
    const rows = [...container.querySelectorAll("tbody tr")].map((row) =>
      [...row.querySelectorAll("td")].map((cell) => cell.textContent),
    );

    expect(rows).toEqual([
      ["Snap% (L3)", "66%", "40%"],
      ["Proj", "9.88", "8.20"],
      ["Opp", "vs DAL, 6th-easiest", "vs KC, 2nd-toughest"],
    ]);
  });

  it("says which way each player goes and where he stands, in words", async () => {
    const { container } = await render(<ActionList actions={[swap]} />);
    const heads = [...container.querySelectorAll("thead th")].map((cell) => cell.textContent);

    expect(heads).toEqual(["", "InChimere Dikefree agent", "OutAntonio Williamsbench"]);
  });

  it("keeps a move of one player compact, with no table", async () => {
    const { container } = await render(<ActionList actions={[{ ...action("one"), players: [dike] }]} />);

    expect(container.querySelector("table")).toBeNull();
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

describe("players compared", () => {
  it("lets a figure that is the app's own measure explain itself, and leaves the league's plain", async () => {
    const valued = (name: string): MovePlayer => ({
      ...player("in", name, "free agent", ["", "", ""]),
      figures: [
        { label: "Value/g", value: "1.2", tone: "neutral", url: "", better: null, hint: "A game's worth across the categories." },
        { label: "Weak in", value: "FG% .380", tone: "neutral", url: "", better: null, hint: "" },
      ],
    });
    const { container } = await render(<Compared players={[valued("A"), valued("B")]} />);

    const explained = [...container.querySelectorAll("[aria-label]")].map((el) => el.getAttribute("aria-label"));
    expect(explained).toEqual(["Value/g: A game's worth across the categories."]);
    expect(container.textContent).toContain("Weak inFG% .380FG% .380");
  });
});

describe("what an item opens", () => {
  const dike = player("in", "Chimere Dike", "free agent", ["66%", "9.88", "vs DAL"]);
  const williams = player("out", "Antonio Williams", "bench", ["40%", "8.20", "vs KC"]);

  it("opens the players a move weighs side by side, each said to be coming in or going out", () => {
    const onOpen = vi.fn();
    const onCompare = vi.fn();
    const swap: Action = { ...action("dike"), player_id: dike.player_id, players: [dike, williams] };

    opener(swap, onOpen, onCompare)!();

    expect(onOpen).not.toHaveBeenCalled();
    expect(onCompare).toHaveBeenCalledWith({
      ids: ["Chimere Dike", "Antonio Williams"],
      title: "Pick up dike",
      tags: { "Chimere Dike": "In", "Antonio Williams": "Out" },
    });
  });

  it("opens the one player an item is about, and nothing where it is about nobody", () => {
    const onOpen = vi.fn();
    const single: Action = { ...action("lions"), player_id: "DET", players: [] };

    opener(single, onOpen, vi.fn())!();

    expect(onOpen).toHaveBeenCalledWith("DET");
    expect(opener(action("trade"), onOpen, vi.fn())).toBeUndefined();
  });

  it("falls back to the one player where the page cannot compare", () => {
    const onOpen = vi.fn();
    const swap: Action = { ...action("dike"), player_id: dike.player_id, players: [dike, williams] };

    opener(swap, onOpen)!();

    expect(onOpen).toHaveBeenCalledWith("Chimere Dike");
  });
});
