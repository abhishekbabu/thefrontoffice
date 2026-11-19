import { act, useState } from "react";
import { describe, expect, it } from "vitest";
import { ToggleChip, ToggleGroup } from "@/components/ui/toggle";
import { render } from "@/test/render";

function Teams({ grouped = true }: { grouped?: boolean }) {
  const [picked, setPicked] = useState("a");
  const chips = ["a", "b", "c"].map((id) => (
    <ToggleChip key={id} pressed={picked === id} onClick={() => setPicked(id)}>
      {id}
    </ToggleChip>
  ));
  return grouped ? <ToggleGroup>{chips}</ToggleGroup> : <>{chips}</>;
}

const chip = (container: HTMLElement, id: string) =>
  [...container.querySelectorAll("button")].find((b) => b.textContent === id)!;
const markers = (container: HTMLElement) => container.querySelectorAll("button > [aria-hidden]");

describe("ToggleChip", () => {
  it("in a group, carries one marker, on the chip chosen, which moves with the choice", async () => {
    const { container } = await render(<Teams />);
    expect(markers(container)).toHaveLength(1);
    expect(chip(container, "a").querySelector("[aria-hidden]")).not.toBeNull();

    await act(async () => chip(container, "c").click());

    expect(markers(container)).toHaveLength(1);
    expect(chip(container, "c").querySelector("[aria-hidden]")).not.toBeNull();
    expect(chip(container, "c").getAttribute("aria-pressed")).toBe("true");
  });

  it("alone, is filled itself, with no marker to share", async () => {
    const { container } = await render(<Teams grouped={false} />);
    expect(markers(container)).toHaveLength(0);
    expect(chip(container, "a").getAttribute("aria-pressed")).toBe("true");
  });
});
