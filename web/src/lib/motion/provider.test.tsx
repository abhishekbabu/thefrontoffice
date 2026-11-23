import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { m } from "motion/react";
import { animating, render, settle } from "@/test/render";

declare global {
  /** The test DOM's own controls, which happy-dom hangs on its window. */
  interface Window {
    happyDOM: { settings: { device: { prefersReducedMotion: string } } };
  }
}

/**
 * The system's "reduce motion" setting, flipped in the test DOM itself.
 * Motion reads it once and then follows its change event, which happy-dom
 * sends for a media query whose answer changes on the next resize.
 */
function setReduce(next: boolean) {
  window.happyDOM.settings.device.prefersReducedMotion = next ? "reduce" : "no-preference";

  window.dispatchEvent(new Event("resize"));
}

beforeAll(() => {
  // From no preference, so the switch to "reduce" is a change: happy-dom
  // sends one only for an answer unlike the one it saw as Motion subscribed.
  setReduce(false);
});

afterAll(() => {
  setReduce(false);
});

// The suite skips every animation; these tests are about whether one runs.
animating();

/**
 * A drawer's worth of travel, 50ms into its 300. Left to finish before the
 * test ends: the test DOM rejects an animation cancelled by unmounting.
 */
async function moving() {
  const { container } = await render(
    <m.div data-moving initial={{ x: 100 }} animate={{ x: 0 }} transition={{ duration: 0.3 }} />,
  );

  await settle(50);

  return container.querySelector<HTMLElement>("[data-moving]")!;
}

describe("motion under the system's reduce-motion setting", () => {
  it("moves for a viewer who has not asked for less", async () => {
    expect((await moving()).style.transform).toMatch(/translateX\(\d/);

    await settle(400);
  });

  it("puts movement at its end at once once the viewer asks for less", async () => {
    setReduce(true);

    expect((await moving()).style.transform).toBe("none");
  });
});
