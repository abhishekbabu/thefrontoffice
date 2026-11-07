/**
 * Rendering a component into the test DOM, as the app shell would host it.
 *
 * The suite has no testing library: React's own `act` and the DOM are enough
 * to put a component on a page, press keys at it and read what it shows.
 * Motion runs with its features loaded at once and every animation skipped,
 * so what is asserted is the state a component settles in, not a frame of it.
 */
import { act, type ReactNode } from "react";
import { afterEach } from "vitest";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LazyMotion, MotionGlobalConfig } from "motion/react";
import features from "@/lib/motion-features";
import { TooltipProvider } from "@/components/ui/tooltip";

// Tells React this is a test environment, so `act` flushes as it would in one.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
// Every animation jumps to its end: the test DOM has no animation clock to run one on.
MotionGlobalConfig.skipAnimations = true;

/**
 * A query client that never asks the network: every answer a test needs is
 * put in it beforehand, and kept fresh so nothing refetches it.
 */
export function offlineClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, enabled: true } } });
}

const mounted = new Set<() => Promise<void>>();

// Each test starts on an empty page: a dialog left open by the last one would
// be the first thing the next one finds.
afterEach(async () => {
  for (const unmount of mounted) await unmount();
});

export type Rendered = {
  container: HTMLElement;
  rerender: (ui: ReactNode) => Promise<void>;
  unmount: () => Promise<void>;
};

export async function render(ui: ReactNode, client: QueryClient = offlineClient()): Promise<Rendered> {
  const container = document.createElement("div");
  document.body.append(container);
  const root: Root = createRoot(container);
  const wrap = (node: ReactNode) => (
    <QueryClientProvider client={client}>
      <LazyMotion features={features}>
        <TooltipProvider>{node}</TooltipProvider>
      </LazyMotion>
    </QueryClientProvider>
  );
  const unmount = async () => {
    mounted.delete(unmount);
    await act(async () => root.unmount());
    container.remove();
  };
  mounted.add(unmount);
  await act(async () => root.render(wrap(ui)));
  return { container, rerender: (next) => act(async () => root.render(wrap(next))), unmount };
}

/** Press `key` on `target`, as a keyboard would: down, letting React and the page respond. */
export async function press(target: Element, key: string, init: KeyboardEventInit = {}): Promise<KeyboardEvent> {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
  await act(async () => {
    target.dispatchEvent(event);
  });
  return event;
}

/** Let pending effects, timers and exit animations settle. */
export async function settle(ms = 50): Promise<void> {
  await act(async () => new Promise((resolve) => setTimeout(resolve, ms)));
}
