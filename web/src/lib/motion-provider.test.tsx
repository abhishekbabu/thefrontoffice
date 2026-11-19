import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { m, MotionGlobalConfig } from "motion/react";
import { render, settle } from "@/test/render";

/**
 * The system's "reduce motion" setting, as the page reads it. Motion reads it
 * once and then follows its change event, so the setting is flipped through
 * that event rather than by asking again.
 */
let reduce = true;
const listeners: (() => void)[] = [];

function setReduce(next: boolean) {
  reduce = next;
  for (const listener of listeners) listener();
}

beforeAll(() => {
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        media: query,
        get matches() {
          return query.includes("reduced-motion") && reduce;
        },
        addEventListener: (_: string, listener: () => void) => listeners.push(listener),
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
  // The suite skips every animation; these tests are about whether one runs.
  MotionGlobalConfig.skipAnimations = false;
});

afterAll(() => {
  MotionGlobalConfig.skipAnimations = true;
  vi.restoreAllMocks();
});

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
  it("puts movement at its end at once for a viewer who asked for less", async () => {
    setReduce(true);
    expect((await moving()).style.transform).toBe("none");
  });

  it("still moves for everyone else", async () => {
    setReduce(false);
    expect((await moving()).style.transform).toMatch(/translateX\(\d/);
    await settle(400);
  });
});
