import { describe, expect, it, vi } from "vitest";
import { clickable } from "@/lib/clickable";
import { press, render } from "@/test/render";

async function row(open?: () => void, inside = false) {
  const { container } = await render(
    <div data-testid="row" {...clickable(open)}>
      {inside && <input aria-label="inside" />}
    </div>,
  );
  return container.querySelector<HTMLElement>("[data-testid=row]")!;
}

describe("a clickable row", () => {
  it("opens on Enter and on Space, as a button does", async () => {
    const open = vi.fn();
    const target = await row(open);

    await press(target, "Enter");
    const space = await press(target, " ");

    expect(open).toHaveBeenCalledTimes(2);
    // Space would otherwise also scroll the page.
    expect(space.defaultPrevented).toBe(true);
  });

  it("is announced and reachable as a button", async () => {
    const target = await row(() => {});
    expect([target.getAttribute("role"), target.tabIndex]).toEqual(["button", 0]);
  });

  it("leaves the keys of a control inside it to that control", async () => {
    const open = vi.fn();
    const target = await row(open, true);

    await press(target.querySelector("input")!, " ");

    expect(open).not.toHaveBeenCalled();
  });

  it("is not a button at all where there is nothing to open", async () => {
    const target = await row(undefined);
    expect([target.getAttribute("role"), target.getAttribute("tabindex")]).toEqual([null, null]);
  });

  it("keeps a table row a row", () => {
    expect(clickable(() => {}, { role: null })).not.toHaveProperty("role");
  });
});
