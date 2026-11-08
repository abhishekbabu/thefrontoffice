import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import type { Turn } from "@/lib/api";
import { Thread } from "@/components/ui/chat";
import { render, settle } from "@/test/render";

const ASKED: Turn[] = [
  { role: "you", text: "Why bench him?" },
  { role: "model", text: "He has no fixture." },
];

/**
 * A server holding one conversation per thread opened: `opened` counts the
 * threads, and each follow-up answers with every turn so far, as the API does.
 */
function server(said: Turn[] = []) {
  const state = { opened: 0, turns: [...said] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path.endsWith("/threads")) {
        state.opened += 1;
        return Response.json({ chat_id: `chat-${state.opened}` });
      }
      if (init?.method === "POST") {
        const { message } = JSON.parse(String(init.body)) as { message: string };
        state.turns.push({ role: "you", text: message }, { role: "model", text: `About: ${message}` });
      }
      return Response.json(state.turns);
    }),
  );
  return state;
}

/** The app's own defaults that matter here: nothing refetched on a timer, nothing retried. */
function client(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } });
}

const thread = <Thread competition="nfl-sleeper" league="900" subject={{ kind: "task", key: "swap:a:b" }} placeholder="Ask" />;

/** The questions on screen, oldest first. */
function questions(container: HTMLElement): (string | null)[] {
  return [...container.querySelectorAll("p.whitespace-pre-line")].map((node) => node.textContent);
}

async function ask(container: HTMLElement, question: string) {
  const input = container.querySelector("input")!;
  const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  await act(async () => {
    setValue.call(input, question);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    container.querySelector("form")!.requestSubmit();
  });
  await settle();
}

let scrolled: ReturnType<typeof vi.fn<(arg?: boolean | ScrollIntoViewOptions) => void>>;

beforeEach(() => {
  scrolled = vi.fn<(arg?: boolean | ScrollIntoViewOptions) => void>();
  Element.prototype.scrollIntoView = scrolled;
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("a conversation about one thing", () => {
  it("finds the same conversation when reopened long after it was closed", async () => {
    // Past the query cache's five-minute default, which dropped the id and
    // opened a blank conversation beside the one the server still held.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const state = server(ASKED);
    const queries = client();
    const first = await render(thread, queries);
    await settle();
    await first.unmount();

    await act(async () => vi.advanceTimersByTime(30 * 60_000));
    const again = await render(thread, queries);
    await settle();

    expect(state.opened).toBe(1);
    expect(again.container.textContent).toContain("He has no fixture.");
  });

  it("does not scroll to the turns it reads back on opening", async () => {
    // In the player drawer that carried the page past everything above the chat.
    server(ASKED);
    const { container } = await render(thread, client());
    await settle();

    expect(container.textContent).toContain("He has no fixture.");
    expect(scrolled).not.toHaveBeenCalled();
  });

  it("keeps a question asked here, and its answer, in view", async () => {
    server(ASKED);
    const { container } = await render(thread, client());
    await settle();

    await ask(container, "And next week?");

    expect(container.textContent).toContain("About: And next week?");
    expect(scrolled).toHaveBeenCalled();
  });

  it("shows the conversation the server answers with rather than a copy of its own", async () => {
    const state = server(ASKED);
    const { container } = await render(thread, client());
    await settle();
    // Asked since from another tab: only the server's record has it.
    state.turns.push({ role: "you", text: "Elsewhere?" }, { role: "model", text: "Yes." });

    await ask(container, "And next week?");

    expect(questions(container)).toEqual(["Why bench him?", "Elsewhere?", "And next week?"]);
  });
});
