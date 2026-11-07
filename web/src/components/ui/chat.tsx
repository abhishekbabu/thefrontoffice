import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { SendHorizontal } from "lucide-react";
import { IconButton } from "@/components/ui/icon-button";
import { Busy } from "@/components/ui/state";
import { Input } from "@/components/ui/input";
import { Prose } from "@/components/ui/prose";
import { cn } from "@/lib/utils";

export type Turn = { role: "you" | "model"; text: string; failed?: boolean };

/**
 * What has been said in each conversation, for as long as the page lives.
 *
 * A conversation outlives the component showing it: switching league and
 * back, or minimizing, should find the turns where they were, since the
 * server still holds the conversation they belong to.
 */
const TRANSCRIPTS = new Map<string, Turn[]>();

/**
 * One conversation's turns, and the way to add one.
 *
 * `ask` sends a question and resolves to the answer; whatever it needs
 * besides the words — what is on screen — it closes over at the moment it is
 * called. A failure is a turn too, in the destructive colour, so the question
 * it answers does not just sit there unanswered.
 */
export function useConversation<T>(id: string, ask: (message: string, extra: T) => Promise<{ answer: string }>) {
  const [turns, setTurns] = useState<Turn[]>(() => TRANSCRIPTS.get(id) ?? []);
  useEffect(() => {
    TRANSCRIPTS.set(id, turns);
  }, [id, turns]);

  const send = useMutation({
    mutationFn: ({ message, extra }: { message: string; extra: T }) => ask(message, extra),
    onSuccess: (reply) => setTurns((t) => [...t, { role: "model", text: reply.answer }]),
    onError: (e: Error) => setTurns((t) => [...t, { role: "model", text: e.message, failed: true }]),
  });

  function say(message: string, extra: T) {
    setTurns((t) => [...t, { role: "you", text: message }]);
    send.mutate({ message, extra });
  }

  return { turns, pending: send.isPending, say };
}

/**
 * A conversation with the model, and the box to continue it.
 *
 * Only what is said and the box: the frame around it, and what the
 * conversation is about, belong to whoever holds it.
 */
export function Chat({
  turns,
  pending,
  onSend,
  placeholder,
  empty,
}: {
  turns: Turn[];
  pending: boolean;
  onSend: (message: string) => void;
  placeholder: string;
  /** Shown before anything has been said. */
  empty?: React.ReactNode;
}) {
  const [draft, setDraft] = useState("");

  // The box is under the conversation, so keeping it in view keeps the newest
  // turn in view too — the answer otherwise lands below the fold.
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (turns.length) form.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [turns.length, pending]);

  function send(e: React.FormEvent) {
    e.preventDefault();
    const message = draft.trim();
    if (!message || pending) return;
    setDraft("");
    onSend(message);
  }

  // At least as tall as whatever holds it, so the box sits at the foot of a
  // panel rather than wherever the conversation so far happens to end.
  return (
    <div className="flex min-h-full flex-col gap-3">
      {turns.length === 0 && !pending && empty}
      {turns.map((turn, i) => (
        <Bubble key={i} role={turn.role}>
          {turn.role === "model" && !turn.failed ? (
            <Prose text={turn.text} />
          ) : (
            <p className={cn("whitespace-pre-line", turn.failed && "text-destructive")}>{turn.text}</p>
          )}
        </Bubble>
      ))}
      {/* Where the answer will be, so waiting reads as the turn it is. */}
      {pending && (
        <Bubble role="model">
          <span className="text-muted-foreground">
            <Busy>Thinking…</Busy>
          </span>
        </Bubble>
      )}
      <form ref={form} onSubmit={send} className="mt-auto flex gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={placeholder}
          aria-label={placeholder}
          className="flex-1"
        />
        <IconButton
          label="Ask"
          side="left"
          variant="primary"
          type="submit"
          icon={<SendHorizontal />}
          disabled={!draft.trim() || pending}
          className="size-9"
        />
      </form>
    </div>
  );
}

/** One turn: yours to the right in a tint, the model's at full width of the column. */
function Bubble({ role, children }: { role: Turn["role"]; children: React.ReactNode }) {
  return (
    <div className={cn("flex max-w-[72ch] flex-col gap-0.5 text-[13.5px] leading-relaxed", role === "you" && "items-end self-end")}>
      <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">{role}</div>
      <div className={cn(role === "you" && "rounded-md bg-muted px-3 py-2")}>{children}</div>
    </div>
  );
}
