import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Eye, Minus, RotateCcw, Sparkles } from "lucide-react";
import { m } from "motion/react";
import { api, type Competition, type League } from "@/lib/api";
import { dock } from "@/lib/motion";
import type { Route } from "@/lib/route";
import { onScreen, useAssistantOpen, useAsked, useOpened, type Asked, type Shown } from "@/lib/screen";
import { Chat, useConversation } from "@/components/ui/chat";
import { ErrorNote } from "@/components/ui/error-note";
import { IconButton } from "@/components/ui/icon-button";
import { Busy } from "@/components/ui/state";
import { cn } from "@/lib/utils";

/**
 * The assistant: one conversation per league, docked in the corner of every page.
 *
 * It follows you rather than living on a page, so a question can be about
 * whatever you are looking at — the week, the table, the wire, a player you
 * have open — and the next one about something else without starting again.
 * Each question carries what is on screen as it is asked; the server briefs
 * the model on whatever of that it has not seen yet.
 *
 * Off the league pages it keeps the last league you were in, since that is
 * the conversation you were having. Minimized, it is hidden rather than
 * unmounted, so opening it again finds the conversation where it was.
 */
export function Assistant({
  route,
  competition,
  league,
}: {
  route: Route;
  competition?: Competition;
  league?: League;
}) {
  const last = useRef<{ competition: Competition; league: League } | null>(null);
  if (competition && league) last.current = { competition, league };
  const target = last.current;

  const [open, setOpen] = useAssistantOpen();
  const [generation, setGeneration] = useState(0);
  const shown = onScreen(route, useOpened());
  const [asked, taken] = useAsked();

  // Not opened on the server until the assistant is first opened: a
  // conversation per page load that nobody uses is a model session for
  // nothing. Kept once it has one, minimized or not.
  const thread = useQuery({
    queryKey: ["assistant", target?.competition.key, target?.league.league_id, generation],
    queryFn: () => api.openAssistant(target!.competition.key, target!.league.league_id),
    enabled: Boolean(target) && open,
    staleTime: Infinity,
  });

  return (
    <>
      {!open && (
        <IconButton
          label="Ask the assistant"
          side="left"
          variant="primary"
          icon={<Sparkles />}
          onClick={() => setOpen(true)}
          className="fixed right-5 bottom-5 z-[60] size-11 rounded-full shadow-lg"
        />
      )}
      <m.section
        variants={dock}
        initial="hidden"
        animate={open ? "shown" : "hidden"}
        aria-label="Assistant"
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className={cn(
          "fixed right-4 bottom-4 z-[60] flex flex-col overflow-hidden rounded-lg border border-border bg-popover shadow-lg",
          "h-[min(36rem,calc(100dvh-2rem))] w-[min(26rem,calc(100vw-2rem))]",
        )}
      >
        <header className="flex items-center justify-between gap-3 border-b border-border py-1.5 pr-1.5 pl-4">
          <span className="flex min-w-0 items-center gap-2">
            <Sparkles className="size-3.5 shrink-0 text-primary" aria-hidden />
            <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              Assistant
            </span>
            {target && <span className="truncate text-[12px] text-muted-foreground">{target.league.name}</span>}
          </span>
          <span className="flex shrink-0 items-center">
            <IconButton
              label="New conversation"
              side="bottom"
              icon={<RotateCcw />}
              onClick={() => setGeneration((g) => g + 1)}
              disabled={!thread.data}
            />
            <IconButton label="Minimize" side="bottom" icon={<Minus />} onClick={() => setOpen(false)} />
          </span>
        </header>

        <Context shown={shown} />

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {!target ? (
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Open one of your leagues, then ask about anything on it.
            </p>
          ) : thread.isError ? (
            <ErrorNote error={thread.error} className="m-0" />
          ) : !thread.data ? (
            <span className="text-[12.5px] text-muted-foreground">
              <Busy>Opening…</Busy>
            </span>
          ) : (
            <Conversation key={thread.data.chat_id} chatId={thread.data.chat_id} shown={shown} asked={asked} taken={taken} />
          )}
        </div>
      </m.section>
    </>
  );
}

/**
 * The conversation itself, once the server holds one.
 *
 * Sends a question asked from elsewhere — a "Why?" on a to-do item — as soon
 * as it can, with what that question was about beside what is on screen.
 */
function Conversation({
  chatId,
  shown,
  asked,
  taken,
}: {
  chatId: string;
  shown: Shown[];
  asked: Asked | null;
  taken: () => void;
}) {
  const { turns, pending, say } = useConversation(chatId, (message, about: Shown[]) =>
    api.assist(
      chatId,
      message,
      about.map((s) => s.subject),
    ),
  );

  useEffect(() => {
    if (!asked) return;
    taken();
    say(asked.message, [...shown, ...asked.about]);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per question handed over, not per render.
  }, [asked]);

  return (
    <Chat
      turns={turns}
      pending={pending}
      onSend={(message) => say(message, shown)}
      placeholder="Ask about this page"
      empty={
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          Ask about anything on screen — the week, the table, your roster, the wire, or a player you have open.
        </p>
      }
    />
  );
}

/**
 * What the assistant can see, under its header.
 *
 * Said rather than implied: an answer about the wrong page is a mystery
 * unless you can see what the question was asked with.
 */
function Context({ shown }: { shown: Shown[] }) {
  return (
    <p className="flex items-center gap-1.5 border-b border-border/45 px-4 py-1.5 font-mono text-[11px] text-muted-foreground">
      <Eye className="size-3 shrink-0" aria-hidden />
      <span className="truncate">{shown.length ? shown.map((s) => s.label).join(" · ") : "Nothing of a league"}</span>
    </p>
  );
}
