import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { SendHorizontal } from "lucide-react";
import { api, type Subject } from "@/lib/api";
import { IconButton } from "@/components/ui/icon-button";
import { Card, CardHeader } from "@/components/ui/card";
import { Busy } from "@/components/ui/state";
import { Input } from "@/components/ui/input";
import { Prose } from "@/components/ui/prose";
import { ErrorNote } from "@/components/ui/error-note";
import { cn } from "@/lib/utils";

/** Conversations whose opener has been asked, for as long as the page lives. */
const OPENED = new Set<string>();

/**
 * A conversation with the model about something already on screen.
 *
 * `opener` is asked once, as soon as the conversation exists — a "Why?" is a
 * question the person already asked by pressing it. `bare` drops the card
 * for a conversation that lives inside something else, such as a to-do row.
 */
export function Chat({
  chatId,
  title = "Ask a follow-up",
  placeholder = "Why that move?",
  opener,
  bare = false,
}: {
  chatId: string;
  title?: string;
  placeholder?: string;
  opener?: string;
  bare?: boolean;
}) {
  // The opener is shown from the first render, as the question it already is.
  const [turns, setTurns] = useState<Turn[]>(() =>
    opener && !OPENED.has(chatId) ? [{ role: "you", text: opener }] : [],
  );
  const [draft, setDraft] = useState("");

  const ask = useMutation({
    mutationFn: (message: string) => api.ask(chatId, message),
    onSuccess: (reply) => setTurns((t) => [...t, { role: "model", text: reply.answer }]),
    onError: (e: Error) => setTurns((t) => [...t, { role: "model", text: e.message, failed: true }]),
  });

  function say(message: string) {
    setTurns((t) => [...t, { role: "you", text: message }]);
    ask.mutate(message);
  }

  // Once per conversation, however often the component mounts: a second
  // copy of the opener would be a second question nobody asked, sent into
  // the same conversation on the server.
  useEffect(() => {
    if (opener && !OPENED.has(chatId)) {
      OPENED.add(chatId);
      ask.mutate(opener);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs per conversation, not per render.
  }, [chatId, opener]);

  // The box is under the conversation, so keeping it in view keeps the newest
  // turn in view too — in a drawer the answer otherwise lands below the fold.
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (turns.length) form.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [turns.length, ask.isPending]);

  function send(e: React.FormEvent) {
    e.preventDefault();
    const message = draft.trim();
    if (!message || ask.isPending) return;
    setDraft("");
    say(message);
  }

  const body = (
    <div className={cn("flex flex-col gap-3", !bare && "p-4")}>
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
      {ask.isPending && (
        <Bubble role="model">
          <span className="text-muted-foreground">
            <Busy>Thinking…</Busy>
          </span>
        </Bubble>
      )}
      <form ref={form} onSubmit={send} className="flex gap-2">
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
          disabled={!draft.trim() || ask.isPending}
          className="size-9"
        />
      </form>
    </div>
  );

  if (bare) return body;
  return (
    <Card>
      <CardHeader>
        <span>{title}</span>
      </CardHeader>
      {body}
    </Card>
  );
}

type Turn = { role: "you" | "model"; text: string; failed?: boolean };

/** One turn: yours to the right in a tint, the model's at full width of the column. */
function Bubble({ role, children }: { role: Turn["role"]; children: React.ReactNode }) {
  return (
    <div className={cn("flex max-w-[72ch] flex-col gap-0.5 text-[13.5px] leading-relaxed", role === "you" && "items-end self-end")}>
      <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">{role}</div>
      <div className={cn(role === "you" && "rounded-md bg-muted px-3 py-2")}>{children}</div>
    </div>
  );
}

/**
 * A conversation about one subject — a to-do item or a player — opened on
 * the server with that subject and nothing else, then asked like any chat.
 *
 * Kept for the session per subject, so closing and reopening a "Why?" finds
 * the same conversation rather than starting a new one on the server.
 */
export function Thread({
  competition,
  league,
  subject,
  ...chat
}: {
  competition: string;
  league: string;
  subject: Subject;
  title?: string;
  placeholder?: string;
  opener?: string;
  bare?: boolean;
}) {
  const thread = useQuery({
    queryKey: ["thread", competition, league, subject.kind, subject.key],
    queryFn: () => api.thread(competition, league, subject),
    staleTime: Infinity,
  });
  if (thread.isError) return <ErrorNote error={thread.error} className="m-0" />;
  if (!thread.data)
    return (
      <span className="text-[12.5px] text-muted-foreground">
        <Busy>Opening…</Busy>
      </span>
    );
  return <Chat chatId={thread.data.chat_id} {...chat} />;
}
