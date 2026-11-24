import { act } from "react";
import { useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { Summary } from "@/lib/types";
import { DayStepper, useDayParam } from "@/components/league/day-stepper";
import { press, render } from "@/test/render";

type DayRange = NonNullable<Summary["days"]>;

const week = (day: string, today: string | null = "2026-11-24"): DayRange => ({
  day,
  first: "2026-11-23",
  last: "2026-11-29",
  today,
});

function stepping(range: DayRange) {
  const steps: string[] = [];

  return { steps, ui: <DayStepper range={range} onStep={(to) => steps.push(to)} /> };
}

const button = (container: HTMLElement, label: string) =>
  container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);

describe("DayStepper", () => {
  it("names the day each arrow goes to, and steps to it", async () => {
    const { steps, ui } = stepping(week("2026-11-25"));

    const { container } = await render(ui);

    await act(async () => button(container, "Tue 24 Nov")!.click());

    await act(async () => button(container, "Thu 26 Nov")!.click());

    expect(container.querySelector("[aria-live]")?.textContent).toBe("Wed 25 Nov");
    expect(steps).toEqual(["2026-11-24", "2026-11-26"]);
  });

  it("says today is today, and offers the way back to it from any other day of its week", async () => {
    const here = await render(stepping(week("2026-11-24")).ui);

    expect(here.container.textContent).toContain("today");
    expect(button(here.container, "Back to today (Tue 24 Nov)")).toBeNull();

    const { steps, ui } = stepping(week("2026-11-28"));

    const away = await render(ui);

    await act(async () => button(away.container, "Back to today (Tue 24 Nov)")!.click());

    expect(steps).toEqual(["2026-11-24"]);
  });

  it("offers no way back to today from a week that does not hold it", async () => {
    const { container } = await render(stepping(week("2026-11-23", null)).ui);

    expect(container.querySelector('button[aria-label^="Back to today"]')).toBeNull();
    expect(container.textContent).not.toContain("today");
  });

  it("goes no further than the week does, by arrow or by key", async () => {
    const start = stepping(week("2026-11-23"));

    const first = await render(start.ui);

    expect(button(first.container, "Sun 22 Nov")!.disabled).toBe(true);

    await press(window, "ArrowLeft");

    expect(start.steps).toEqual([]);

    await first.unmount();

    const end = stepping(week("2026-11-29"));

    const last = await render(end.ui);

    expect(button(last.container, "Mon 30 Nov")!.disabled).toBe(true);

    await press(window, "ArrowLeft");

    expect(end.steps).toEqual(["2026-11-28"]);
  });
});

function Address({ range, to }: { range: DayRange; to: string }) {
  const { day, step } = useDayParam();
  const { search } = useLocation();

  return (
    <button type="button" data-day={day ?? ""} onClick={() => step(to, range)}>
      {search}
    </button>
  );
}

describe("useDayParam", () => {
  it("names a day in the address beside the week, and leaves off the day the week opens on", async () => {
    const away = await render(<Address range={week("2026-11-24")} to="2026-11-26" />);

    await act(async () => away.container.querySelector("button")!.click());

    expect(away.container.textContent).toBe("?day=2026-11-26");
    expect(away.container.querySelector("button")!.dataset.day).toBe("2026-11-26");

    await away.unmount();

    const home = await render(<Address range={week("2026-11-26")} to="2026-11-24" />);

    await act(async () => home.container.querySelector("button")!.click());

    expect(home.container.textContent).toBe("");
  });
});
