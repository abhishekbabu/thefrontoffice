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
    const rows = [...container.querySelectorAll("[class*=border-t]")].map((r) => r.textContent ?? "");

    expect(rows.find((r) => r.includes("Week 11"))).toContain("Trade deadline");
    expect(rows.find((r) => r.includes("Week 10"))).toContain("live 119.24-103.90");
  });
});
