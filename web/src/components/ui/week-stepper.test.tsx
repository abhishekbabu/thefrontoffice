import { act } from "react";
import { describe, expect, it } from "vitest";
import type { WeekRange } from "@/lib/api";
import { SWIPE_DISTANCE, WeekPane, WeekStepper, useSwipe } from "@/components/ui/week-stepper";
import { render } from "@/test/render";

describe("WeekPane", () => {
  const pane = (week: number, pending = false) => (
    <WeekPane week={week} pending={pending}>
      <p>week {week}</p>
    </WeekPane>
  );

  it("holds the week it shows while the next is still loading, and changes once it arrives", async () => {
    const { container, rerender } = await render(pane(3));
    const first = container.querySelector("p")!.parentElement;

    // The page keeps the last week's content up while the next loads.
    await rerender(pane(4, true));
    expect(container.querySelector("p")!.parentElement).toBe(first);

    await rerender(pane(4));
    expect(container.querySelector("p")!.parentElement).not.toBe(first);
    expect(container.textContent).toBe("week 4");
  });
});

const range = (week: number): WeekRange => ({ week, current: 10, first: 1, last: 16 });

function stepping(week: number) {
  const steps: number[] = [];
  return { steps, ui: <WeekStepper range={range(week)} onStep={(to) => steps.push(to)} /> };
}

const button = (container: HTMLElement, label: string) =>
  container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!;

async function press(key: string, target: EventTarget = window) {
  await act(async () => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  });
}

describe("WeekStepper", () => {
  it("names the week each arrow goes to, and steps to it", async () => {
    const { steps, ui } = stepping(10);
    const { container } = await render(ui);

    await act(async () => button(container, "Week 9").click());
    await act(async () => button(container, "Week 11").click());

    expect(steps).toEqual([9, 11]);
  });

  it("says the week being played is this week, and offers the way back from any other", async () => {
    const here = await render(stepping(10).ui);
    expect(here.container.textContent).toContain("this week");

    const { steps, ui } = stepping(4);
    const away = await render(ui);
    await act(async () => button(away.container, "Back to this week (week 10)").click());
    expect(steps).toEqual([10]);
  });

  it("goes no further than the season does", async () => {
    const start = await render(stepping(1).ui);
    expect(button(start.container, "Week 0").disabled).toBe(true);

    const end = await render(stepping(16).ui);
    expect(button(end.container, "Week 17").disabled).toBe(true);
  });

  it("steps with the arrow keys, but not while something is being typed", async () => {
    const { steps, ui } = stepping(10);
    await render(ui);
    const input = document.body.appendChild(document.createElement("input"));

    await press("ArrowLeft");
    await press("ArrowRight", input);

    expect(steps).toEqual([9]);
    input.remove();
  });
});

function Swipeable({ onNext, onPrevious }: { onNext: () => void; onPrevious: () => void }) {
  return <div data-testid="pane" {...useSwipe(onNext, onPrevious)} />;
}

async function drag(pane: Element, pointerType: string, dx: number, dy = 0) {
  await act(async () => {
    pane.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerType, clientX: 200, clientY: 200 }));
    pane.dispatchEvent(
      new PointerEvent("pointerup", { bubbles: true, pointerType, clientX: 200 + dx, clientY: 200 + dy }),
    );
  });
}

describe("useSwipe", () => {
  it("reads a sideways swipe as the next week leftward and the last week rightward", async () => {
    const seen: string[] = [];
    const { container } = await render(
      <Swipeable onNext={() => seen.push("next")} onPrevious={() => seen.push("previous")} />,
    );
    const pane = container.querySelector("[data-testid=pane]")!;

    await drag(pane, "touch", -SWIPE_DISTANCE - 10);
    await drag(pane, "touch", SWIPE_DISTANCE + 10);

    expect(seen).toEqual(["next", "previous"]);
  });

  it("ignores a mouse drag, a short wobble and a mostly vertical scroll", async () => {
    const seen: string[] = [];
    const { container } = await render(<Swipeable onNext={() => seen.push("next")} onPrevious={() => seen.push("previous")} />);
    const pane = container.querySelector("[data-testid=pane]")!;

    await drag(pane, "mouse", -200);
    await drag(pane, "touch", -20);
    await drag(pane, "touch", -80, 120);

    expect(seen).toEqual([]);
  });
});
