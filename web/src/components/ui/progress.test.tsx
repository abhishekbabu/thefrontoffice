import { describe, expect, it } from "vitest";
import { LoadingBar } from "@/components/ui/progress";
import { render } from "@/test/render";

describe("LoadingBar", () => {
  it("is an indeterminate progress bar, named for what it waits on", async () => {
    const { container } = await render(<LoadingBar label="Loading roster" />);
    const bar = container.querySelector("[role=progressbar]")!;

    expect(bar.getAttribute("aria-label")).toBe("Loading roster");
    // No true progress is known, so it claims none.
    expect(bar.hasAttribute("aria-valuenow")).toBe(false);
  });

  it("carries its state in visible text too, not only in the moving bar", async () => {
    const { container } = await render(<LoadingBar label="Loading roster" />);

    expect(container.textContent).toContain("Loading roster");
  });
});
