import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SendHorizontal } from "lucide-react";
import { api, isExpired, type Subject, type Turn } from "@/lib/api";
import { keys } from "@/lib/queries";
import { IconButton } from "@/components/ui/icon-button";
import { Card, CardHeader } from "@/components/ui/card";
import { Busy } from "@/components/ui/state";
import { Input } from "@/components/ui/input";
import { Prose } from "@/components/ui/prose";
import { ErrorNote } from "@/components/ui/error-note";
import { cn } from "@/lib/utils";
import { Label } from "@/components/ui/label";

/** Conversations whose opener has been asked, for as long as the page lives. */
const OPENED = new Set<string>();

/**
 * A conversation with the model about something already on screen.
 *
 * The turns are the server's: it keeps them, so a conversation closed and
 * reopened shows what was said rather than a blank the server would carry on
 * from. `opener` is asked once, into a conversation with nothing said yet — a
 * "Why?" is a question the person already asked by pressing it. `bare` drops
 * the card for a conversation that lives inside something else, such as a
 * to-do row. `onExpired` is told when the server no longer holds it, with the
 * question that went unasked.
 */
function Chat({
  chatId,
  title,
  placeholder,
  opener,
  bare = false,
  onExpired,
}: ChatProps & { chatId: string; onExpired: (unasked?: string) => void }) {
  const queryClient = useQueryClient();
  const turnsKey = keys.turns(chatId);
  const history = useQuery({ queryKey: turnsKey, queryFn: () => api.turns(chatId), staleTime: 0 });
  // A question the model did not answer: shown with why, never kept by the server.
  const [failed, setFailed] = useState<{ question: string; error: Error } | null>(null);
  const [draft, setDraft] = useState("");

  const ask = useMutation({
    mutationFn: (message: string) => api.ask(chatId, message),
    onMutate: async () => {
      setFailed(null);
      // A read already under way would land without this turn and overwrite it.
      await queryClient.cancelQueries({ queryKey: turnsKey });
    },
    onSuccess: (reply, message) =>
      queryClient.setQueryData<Turn[]>(turnsKey, (turns = []) => [
        ...turns,
        { role: "you", text: message },
        { role: "model", text: reply.answer },
      ]),
    onError: (error: Error, message) => (isExpired(error) ? onExpired(message) : setFailed({ question: message, error })),
  });

  useEffect(() => {
    if (isExpired(history.error)) onExpired();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per failed read, not per render.
  }, [history.error]);

  // Once per conversation, however often the component mounts, and only into
  // one with nothing said: a second copy of the opener would be a second
  // question nobody asked, sent into the same conversation on the server.
  const empty = history.isSuccess && history.data.length === 0;
  useEffect(() => {
    if (opener && empty && !OPENED.has(chatId)) {
      OPENED.add(chatId);
      ask.mutate(opener);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs per conversation, not per render.
  }, [chatId, opener, empty]);

  const turns: Shown[] = [...(history.data ?? [])];
  if (ask.isPending && ask.variables) turns.push({ role: "you", text: ask.variables });
  if (failed) turns.push({ role: "you", text: failed.question }, { role: "model", text: "", error: failed.error });

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
    ask.mutate(message);
  }

  if (history.isError && !isExpired(history.error)) return <ErrorNote error={history.error} className="m-0" />;
  if (!history.data) return <Opening />;

  const body = (
    <div className={cn("flex flex-col gap-3", !bare && "p-4")}>
      {turns.map((turn, i) => (
        <Bubble key={i} role={turn.role}>
          {turn.error ? (
            <ErrorNote error={turn.error} className="m-0" />
          ) : turn.role === "model" ? (
            <Prose text={turn.text} />
          ) : (
            <p className="whitespace-pre-line">{turn.text}</p>
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

/** A turn as shown: the server's, or a question still waiting or one that failed, with why. */
type Shown = Turn & { error?: Error };

type ChatProps = {
  /** The card's heading; a bare conversation has no card to head. */
  title?: string;
  placeholder: string;
  opener?: string;
  bare?: boolean;
};

/** One turn: yours to the right in a tint, the model's at full width of the column. */
function Bubble({ role, children }: { role: Shown["role"]; children: React.ReactNode }) {
  return (
    <div className={cn("flex max-w-[72ch] flex-col gap-0.5 text-[13.5px] leading-relaxed", role === "you" && "items-end self-end")}>
      <Label as="div">{role}</Label>
      <div className={cn(role === "you" && "rounded-md bg-muted px-3 py-2")}>{children}</div>
    </div>
  );
}

function Opening() {
  return (
    <span className="text-[12.5px] text-muted-foreground">
      <Busy>Opening…</Busy>
    </span>
  );
}

/**
 * A conversation about one subject — a to-do item or a player — opened on
 * the server with that subject and nothing else, then asked like any chat.
 *
 * Kept for the session per subject, so closing and reopening a "Why?" finds
 * the same conversation rather than starting a new one on the server — until
 * the server says it no longer holds it, when a fresh one is opened and the
 * question that went unasked is asked there.
 */
export function Thread({
  competition,
  league,
  subject,
  opener,
  ...chat
}: ChatProps & {
  competition: string;
  league: string;
  subject: Subject;
}) {
  const queryClient = useQueryClient();
  const threadKey = keys.thread(competition, league, subject.kind, subject.key);
  const [unasked, setUnasked] = useState<string>();
  const thread = useQuery({
    queryKey: threadKey,
    queryFn: () => api.league(competition, league).thread(subject),
    staleTime: Infinity,
  });

  function reopen(question?: string) {
    setUnasked(question);
    // Dropped and asked again: the kept id is the one the server no longer knows.
    queryClient.resetQueries({ queryKey: threadKey });
  }

  if (thread.isError) return <ErrorNote error={thread.error} className="m-0" />;
  if (!thread.data) return <Opening />;
  const chatId = thread.data.chat_id;
  return <Chat key={chatId} chatId={chatId} opener={unasked ?? opener} onExpired={reopen} {...chat} />;
}
