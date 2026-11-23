import { useMemo, useState } from "react";
import { useKept } from "@/lib/hooks/useKept";
import { Eye, Minus, RotateCcw, Sparkles } from "lucide-react";
import { m } from "motion/react";
import type { Competition, League } from "@/lib/types";
import { dock } from "@/lib/motion/enter";
import type { Route } from "@/lib/route";
import { onScreen, useOpened, type Shown } from "@/lib/screen";
import { useAssistantOpen, useAsked } from "@/lib/asking";
import { AssistantChat, type Asked } from "@/components/league/chat";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Label } from "@/components/ui/label";
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
export function Assistant({ route, competition, league }: { route: Route; competition?: Competition; league?: League }) {
  // Each kept on its own, as they arrive: one object made of the two would be
  // new on every render, and so a change on every render.
  const keptCompetition = useKept(competition && league ? competition : null);
  const keptLeague = useKept(competition && league ? league : null);
  const target = keptCompetition && keptLeague ? { competition: keptCompetition, league: keptLeague } : null;

  const [open, setOpen] = useAssistantOpen();
  const [generation, setGeneration] = useState(0);
  // Opened on the server only once the assistant is first opened: a
  // conversation per page load that nobody uses is a model session for
  // nothing. Kept after, minimized or not.
  const [started, setStarted] = useState(false);

  if (open && !started) setStarted(true);

  const shown = onScreen(route, useOpened());
  const [handed, taken] = useAsked();

  const asked = useMemo<Asked | null>(
    () => handed && { message: handed.message, about: handed.about.map((s) => s.subject) },
    [handed],
  );

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
            <Label>Assistant</Label>
            {target && <span className="truncate text-[12px] text-muted-foreground">{target.league.name}</span>}
          </span>
          <span className="flex shrink-0 items-center">
            <IconButton
              label="New conversation"
              side="bottom"
              icon={<RotateCcw />}
              onClick={() => setGeneration((g) => g + 1)}
              disabled={!target}
            />
            <IconButton label="Minimize" side="bottom" icon={<Minus />} onClick={() => setOpen(false)} />
          </span>
        </header>

        <Context shown={shown} />

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {!target ? (
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Open a league to ask about it.
            </p>
          ) : (
            started && (
              <AssistantChat
                key={`${target.competition.key}:${target.league.league_id}:${generation}`}
                competition={target.competition.key}
                league={target.league.league_id}
                generation={generation}
                onScreen={shown.map((s) => s.subject)}
                asked={asked}
                onTaken={taken}
                placeholder="Ask about this page"
                empty={
                  <p className="text-[13px] leading-relaxed text-muted-foreground">
                    Ask about anything on screen.
                  </p>
                }
              />
            )
          )}
        </div>
      </m.section>
    </>
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
      <span className="truncate">{shown.length ? shown.map((s) => s.label).join(" · ") : "No league open"}</span>
    </p>
  );
}
