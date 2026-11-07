import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { SlideOver } from "@/components/ui/dialog";
import { press, render, settle } from "@/test/render";

/** A page with one button that opens the panel, as a row opens a player. */
function Page({ onClose }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <SlideOver
        open={open}
        label="Josh Allen"
        onClose={() => {
          onClose?.();
          setOpen(false);
        }}
      >
        <button type="button">First</button>
        <button type="button">Last</button>
      </SlideOver>
    </>
  );
}

async function opened(onClose?: () => void) {
  const { container } = await render(<Page onClose={onClose} />);
  const opener = container.querySelector("button")!;
  opener.focus();
  opener.click();
  await settle();
  const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
  return { opener, dialog };
}

describe("a slide-over", () => {
  it("is announced as a modal dialog, named for what it is about", async () => {
    const { dialog } = await opened();

    expect(dialog?.getAttribute("aria-modal")).toBe("true");
    expect(dialog?.getAttribute("aria-label")).toBe("Josh Allen");
  });

  it("takes focus when it opens", async () => {
    const { dialog } = await opened();
    expect(dialog?.contains(document.activeElement)).toBe(true);
  });

  it("closes on Escape and hands focus back to what opened it", async () => {
    const onClose = vi.fn();
    const { opener, dialog } = await opened(onClose);

    await press(dialog!, "Escape");
    await settle(400);

    expect(onClose).toHaveBeenCalledOnce();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("keeps focus inside while it is open", async () => {
    const { dialog } = await opened();
    const [first, last] = dialog!.querySelectorAll("button");

    last!.focus();
    await press(last!, "Tab");
    expect(document.activeElement).toBe(first);

    await press(first!, "Tab", { shiftKey: true });
    expect(document.activeElement).toBe(last);
  });
});
