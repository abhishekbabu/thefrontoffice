import { describe, expect, it } from "vitest";
import { useKept } from "@/lib/useKept";
import { render } from "@/test/render";

function Shown({ value }: { value: string | null }) {
  return <span>{useKept(value) ?? "nothing"}</span>;
}

describe("a kept value", () => {
  it("follows the value, and holds the last one once it goes", async () => {
    const { container, rerender } = await render(<Shown value={null} />);
    expect(container.textContent).toBe("nothing");

    await rerender(<Shown value="Josh Allen" />);
    expect(container.textContent).toBe("Josh Allen");

    await rerender(<Shown value={null} />);
    expect(container.textContent).toBe("Josh Allen");

    await rerender(<Shown value="Jahmyr Gibbs" />);
    expect(container.textContent).toBe("Jahmyr Gibbs");
  });
});
