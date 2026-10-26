import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { SendHorizontal } from "lucide-react";
import { api, type Subject } from "@/lib/api";
import { IconButton } from "@/components/ui/icon-button";
import { Card, CardHeader } from "@/components/ui/card";
import { Busy } from "@/components/ui/state";
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
  const [turns, setTurns] = useState<{ role: "you" | "model"; text: string }[]>(() =>
    opener && !OPENED.has(chatId) ? [{ role: "you", text: opener }] : [],
  );
  const [draft, setDraft] = useState("");

  const ask = useMutation({
    mutationFn: (message: string) => api.ask(chatId, message),
    onSuccess: (reply) => setTurns((t) => [...t, { role: "model", text: reply.answer }]),
    onError: (e: Error) => setTurns((t) => [...t, { role: "model", text: e.message }]),
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
        <div key={i} className={cn("max-w-[62ch] text-[13.5px] leading-relaxed", turn.role === "you" && "self-end")}>
          <div className="mb-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            {turn.role}
          </div>
          <div className={cn(turn.role === "you" ? "rounded-md bg-muted px-3 py-2" : "text-foreground")}>
            {turn.text}
          </div>
        </div>
      ))}
      {bare && ask.isPending && <div className="text-[12.5px] text-muted-foreground">Thinking…</div>}
      <form onSubmit={send} className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={placeholder}
          className="h-9 min-w-0 flex-1 rounded-md border border-input bg-background px-3 text-[13.5px] placeholder:text-muted-foreground"
        />
        <IconButton
          label="Ask"
          side="left"
          variant="primary"
          type="submit"
          icon={<SendHorizontal />}
          disabled={!draft.trim() || ask.isPending}
        />
      </form>
    </div>
  );

  if (bare) return body;
  return (
    <Card>
      <CardHeader>
        <span>{title}</span>
        {ask.isPending && <Busy>Thinking…</Busy>}
      </CardHeader>
      {body}
    </Card>
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
  if (thread.isError) return <ErrorNote error={thread.error} />;
  if (!thread.data) return <div className="text-[12.5px] text-muted-foreground">Opening…</div>;
  return <Chat chatId={thread.data.chat_id} {...chat} />;
}
