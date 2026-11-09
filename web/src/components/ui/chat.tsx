import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SendHorizontal } from "lucide-react";
import { api, isExpired, type Subject, type Turn } from "@/lib/api";
import { keys } from "@/lib/queries";
import { IconButton } from "@/components/ui/icon-button";
import { Busy } from "@/components/ui/state";
import { Input } from "@/components/ui/input";
import { Prose } from "@/components/ui/prose";
import { ErrorNote } from "@/components/ui/error-note";
import { cn } from "@/lib/utils";
import { Label } from "@/components/ui/label";

/**
 * A conversation with the model about whatever is on screen.
 *
 * The turns are the server's: it keeps them, so a conversation closed and
 * reopened shows what was said rather than a blank the server would carry on
 * from. Each question goes with `onScreen`, which the server briefs the model
 * on where it has not yet. `asked` is a question handed over from elsewhere —
 * a "Why?" on a to-do row — sent as soon as the conversation can take it,
 * with what it was about beside what is on screen; `onTaken` says it has been.
 * `onExpired` is told when the server no longer holds the conversation, with
 * the question that went unasked.
 */
function Chat({
  chatId,
  placeholder,
  empty,
  onScreen,
  asked,
  onTaken,
  onExpired,
}: ChatProps & { chatId: string; onExpired: (unasked?: Asked) => void }) {
  const queryClient = useQueryClient();
  const turnsKey = keys.turns(chatId);
  const history = useQuery({ queryKey: turnsKey, queryFn: () => api.turns(chatId), staleTime: 0 });
  // A question the model did not answer: shown with why, never kept by the server.
  const [failed, setFailed] = useState<{ question: string; error: Error } | null>(null);
  const [draft, setDraft] = useState("");

  const ask = useMutation({
    mutationFn: ({ message, about }: Asked) => api.ask(chatId, message, about),
    onMutate: async () => {
      setFailed(null);
      // A read already under way would land without this turn and overwrite it.
      await queryClient.cancelQueries({ queryKey: turnsKey });
    },
    // The server answers with the whole conversation, so the page shows what it holds.
    onSuccess: (turns) => queryClient.setQueryData<Turn[]>(turnsKey, turns),
    onError: (error: Error, asked) =>
      isExpired(error) ? onExpired(asked) : setFailed({ question: asked.message, error }),
  });

  useEffect(() => {
    if (isExpired(history.error)) onExpired();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per failed read, not per render.
  }, [history.error]);

  // Once per question handed over, and only once the conversation has been
  // read: sent before, its turn would be overwritten by the read landing.
  const handled = useRef<Asked | null>(null);
  useEffect(() => {
    if (!asked || asked === handled.current || !history.isSuccess || ask.isPending) return;
    handled.current = asked;
    onTaken();
    ask.mutate({ message: asked.message, about: unique([...onScreen, ...asked.about]) });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- per question handed over, not per render.
  }, [asked, history.isSuccess, ask.isPending]);

  const turns: Shown[] = [...(history.data ?? [])];
  if (ask.isPending && ask.variables) turns.push({ role: "you", text: ask.variables.message });
  if (failed) turns.push({ role: "you", text: failed.question }, { role: "model", text: "", error: failed.error });

  // The box is under the conversation, so keeping it in view keeps the newest
  // turn in view too. Only for a turn asked here: turns read back on opening
  // are not news.
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (!ask.isIdle) form.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [ask.isIdle, ask.status, ask.submittedAt]);

  function send(e: React.FormEvent) {
    e.preventDefault();
    const message = draft.trim();
    if (!message || ask.isPending) return;
    setDraft("");
    ask.mutate({ message, about: onScreen });
  }

  if (history.isError && !isExpired(history.error)) return <ErrorNote error={history.error} className="m-0" />;
  if (!history.data) return <Opening />;

  // At least as tall as whatever holds it, so the box sits at the foot of the
  // panel rather than wherever the conversation so far happens to end.
  return (
    <div className="flex min-h-full flex-col gap-3">
      {turns.length === 0 && !ask.isPending && empty}
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
          disabled={!draft.trim() || ask.isPending}
          className="size-9"
        />
      </form>
    </div>
  );
}

/** A question, and what it was asked about. */
export type Asked = { message: string; about: Subject[] };

/** A turn as shown: the server's, or a question still waiting or one that failed, with why. */
type Shown = Turn & { error?: Error };

type ChatProps = {
  placeholder: string;
  /** Shown before anything has been said. */
  empty?: React.ReactNode;
  /** What is on screen as a question is asked, sent with it. */
  onScreen: Subject[];
  /** A question handed over from elsewhere, to send as soon as the conversation can take it. */
  asked: Asked | null;
  onTaken: () => void;
};

/** The same thing named twice is sent once. */
function unique(subjects: Subject[]): Subject[] {
  return subjects.filter((s, i) => subjects.findIndex((t) => t.kind === s.kind && t.key === s.key) === i);
}

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
 * The assistant's conversation in one league, opened on the server the first
 * time it is shown, then asked like any chat.
 *
 * Kept for the session per league and `generation` — a new conversation is
 * the next generation — so minimizing, moving page or switching league and
 * back finds the same conversation rather than starting a new one on the
 * server, until the server says it no longer holds it: then a fresh one is
 * opened and the question that went unasked is asked there. For the session,
 * not for the query cache's default five minutes, which would drop the id and
 * open a blank conversation beside the one the server still held.
 */
export function AssistantChat({
  competition,
  league,
  generation,
  asked,
  onTaken,
  ...chat
}: ChatProps & { competition: string; league: string; generation: number }) {
  const queryClient = useQueryClient();
  const threadKey = keys.assistant(competition, league, generation);
  const [unasked, setUnasked] = useState<Asked | null>(null);
  const thread = useQuery({
    queryKey: threadKey,
    queryFn: () => api.league(competition, league).assistant(),
    staleTime: Infinity,
    gcTime: Infinity,
  });

  function reopen(question?: Asked) {
    setUnasked(question ?? null);
    // Dropped and asked again: the kept id is the one the server no longer knows.
    queryClient.resetQueries({ queryKey: threadKey });
  }

  if (thread.isError) return <ErrorNote error={thread.error} className="m-0" />;
  if (!thread.data) return <Opening />;
  const chatId = thread.data.chat_id;
  return (
    <Chat
      key={chatId}
      chatId={chatId}
      asked={unasked ?? asked}
      onTaken={() => {
        setUnasked(null);
        onTaken();
      }}
      onExpired={reopen}
      {...chat}
    />
  );
}
