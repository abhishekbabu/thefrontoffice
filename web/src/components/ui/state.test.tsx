import { describe, expect, it } from "vitest";
import { QueryState } from "@/components/ui/state";
import { render } from "@/test/render";

const asked = { isLoading: true, isError: false, error: null };
const answered = { isLoading: false, isError: false, error: null };
const failed = { isLoading: false, isError: true, error: new Error("Yahoo is down") };

describe("QueryState", () => {
  it("shows a progress bar in a polite status region while the query is asked", async () => {
    const { container } = await render(<QueryState query={asked} />);
    const status = container.querySelector("[role=status]")!;

    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.querySelector("[role=progressbar]")).not.toBeNull();
  });

  it("holds more room open for a page with more rows coming", async () => {
    const height = async (lines: number) => {
      const { container } = await render(<QueryState query={asked} lines={lines} />);
      return parseFloat((container.querySelector("[role=status]") as HTMLElement).style.minHeight);
    };

    expect(await height(6)).toBeGreaterThan(await height(2));
  });

  it("shows the failure instead once the query fails", async () => {
    const { container } = await render(<QueryState query={failed} />);

    expect(container.querySelector("[role=progressbar]")).toBeNull();
    expect(container.textContent).toContain("Yahoo is down");
  });

  it("renders nothing once the answer is in", async () => {
    const { container } = await render(<QueryState query={answered} />);

    expect(container.querySelector("[role=progressbar]")).toBeNull();
    expect(container.textContent).toBe("");
  });
});
