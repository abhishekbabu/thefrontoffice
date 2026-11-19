import { describe, expect, it } from "vitest";
import type { ScheduleRow } from "@/lib/api";
import { Season } from "@/panels/Schedule";
import { render } from "@/test/render";

const row = (label: string, extra: Partial<ScheduleRow> = {}): ScheduleRow => ({
  label,
  date: "",
  opponent: "rival",
  detail: "",
  result: "",
  outcome: null,
  is_current: false,
  marks: [],
  playoffs: false,
  ...extra,
});

describe("Season", () => {
  it("names what else falls in a week beside it, in words", async () => {
    const { container } = await render(
      <Season rows={[row("Week 10", { is_current: true, result: "119.24-103.90" }), row("Week 11", { marks: ["Trade deadline"] })]} />,
    );

    expect(container.textContent).toMatch(/Week 10.*live 119\.24-103\.90.*Week 11.*Trade deadline/);
  });

  it("puts the opponent's record now beside their name for a week still to be decided", async () => {
    const { container } = await render(<Season rows={[row("Week 12", { opponent: "Rival", detail: "4-6" })]} />);
    expect(container.textContent).toContain("Rival4-6");
    expect(container.querySelector("[aria-label='Record now 4-6']")).not.toBeNull();
  });

  it("shows no record for a week already decided, which would read as theirs at the time", async () => {
    const played = row("Week 3", { opponent: "Rival", detail: "5-5", result: "140.19-132.14", outcome: "won" });
    const { container } = await render(<Season rows={[played]} />);

    expect(container.textContent).not.toContain("5-5");
    expect(container.textContent).toContain("RivalW 140.19-132.14");
  });

  it("keeps a playoff round beside the opponent once the week is decided", async () => {
    const final = row("Week 17", { opponent: "Rival", detail: "Final", playoffs: true, result: "1-2", outcome: "lost" });
    const { container } = await render(<Season rows={[final]} />);

    expect(container.textContent).toContain("RivalFinalL 1-2");
  });
});
