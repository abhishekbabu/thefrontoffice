import { Subscription, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Schema, Stream } from "effect";
import { AssistantProvider, AssistantProviderMessage } from "@/components/league/assistant-provider";
import { AssistantChat, type Asked } from "@/components/league/chat";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Icon } from "@/components/ui/icon";
import { Label } from "@/components/ui/label";
import type { Route } from "@/lib/route";
import { onScreen, type Shown } from "@/lib/screen";
import type { Competition, League } from "@/lib/types";
import { cn } from "@/lib/utils";
import { wire } from "@/lib/wire";

const Target = Schema.Struct({
  competition: wire<Competition>(),
  league: wire<League>(),
});

type Target = typeof Target.Type;

const AssistantMessage = UiSchema.TaggedEnum({
  ClickedOpen: {},
  ClickedMinimize: {},
  PressedEscape: {},
  ClickedNewConversation: {},
  /** A league page put a league on screen: the conversation to keep having off it. */
  ArrivedLeague: { target: Target },
  /** The provider opened or minimized the assistant: from here, or from a question handed to it. */
  ChangedDock: { open: Schema.Boolean },
  TookChatAsked: {},
});

const AssistantProps = Schema.Struct({
  route: wire<Route>(),
  competition: Schema.NullOr(wire<Competition>()),
  league: Schema.NullOr(wire<League>()),
});

type AssistantProps = typeof AssistantProps.Type;

/** The league on screen, when there is one. */
function onPage({ competition, league }: AssistantProps): Target | null {
  return competition !== null && league !== null ? { competition, league } : null;
}

/**
 * Docked in the corner, opening out of the button that stands for it.
 *
 * Hidden rather than unmounted: what it holds — a conversation half read —
 * should be exactly where it was when it opens again. `display` transitions
 * as a discrete step after the fade (`transition-discrete`), and
 * `@starting-style` (`starting:`) is where it fades in from once shown.
 */
const DOCK = cn(
  "fixed right-4 bottom-4 z-[60] flex-col overflow-hidden rounded-lg border border-border bg-popover shadow-lg",
  "h-[min(36rem,calc(100dvh-2rem))] w-[min(26rem,calc(100vw-2rem))]",
  "transition-[display,opacity,translate,scale] transition-discrete",
);

const DOCKED = "flex opacity-100 duration-180 ease-quick starting:translate-y-3 starting:scale-98 starting:opacity-0";

const MINIMIZED = "hidden translate-y-3 scale-98 opacity-0 duration-120";

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
export const Assistant = Html.component({
  name: "Assistant",
  props: AssistantProps,
  model: Schema.Struct({
    /** The last league a page had on screen. */
    kept: Schema.NullOr(Target),
    /** A new conversation is the next generation. */
    generation: Schema.Number,
    /**
     * Opened on the server only once the assistant is first opened: a
     * conversation per page load that nobody uses is a model session for
     * nothing. Kept after, minimized or not.
     */
    started: Schema.Boolean,
  }),
  message: AssistantMessage,
  reads: {
    provider: {
      owner: AssistantProvider,
      onChange: ({ open }) => AssistantMessage.ChangedDock({ open }),
    },
  },
}).make({
  init: ($) => ({ kept: onPage($.props), generation: 0, started: false }),
  // A prop change dispatches nothing, so the league is kept by a Subscription
  // per league: each starts once, as a page puts that league on screen.
  subscriptions: ({ props }) => {
    const target = onPage(props);

    return [
      target !== null &&
        Subscription.make("league", [target.competition.key, target.league.league_id], () =>
          Stream.make(AssistantMessage.ArrivedLeague({ target })),
        ),
    ];
  },
  update: {
    ClickedOpen: ($) => $.send(AssistantProvider, AssistantProviderMessage.RequestedDock({ open: true })),
    ClickedMinimize: ($) => $.send(AssistantProvider, AssistantProviderMessage.RequestedDock({ open: false })),
    PressedEscape: ($) => $.send(AssistantProvider, AssistantProviderMessage.RequestedDock({ open: false })),
    ClickedNewConversation: ($) => $.evolve({ generation: (g) => g + 1 }),
    ArrivedLeague: ($, { target }) => $.evolve({ kept: target }),
    ChangedDock: ($, { open }) => (open ? $.evolve({ started: true }) : $.model),
    TookChatAsked: ($) => $.send(AssistantProvider, AssistantProviderMessage.TookAsked()),
  },
  view: (h, model) => {
    const { open, asked: handed, opened } = h.reads.provider;
    const target = onPage(h.props) ?? model.kept;
    const shown = onScreen(h.props.route, opened);
    const asked: Asked | null = handed && { message: handed.message, about: handed.about.map((s) => s.subject) };

    return h.div.class("contents").children(
      !open &&
        IconButton(h, {
          key: "open",
          props: {
            label: "Ask the assistant",
            side: "left",
            variant: "primary",
            icon: "sparkles",
            class: "fixed right-5 bottom-5 z-[60] size-11 rounded-full shadow-lg",
          },
          onEmit: { Clicked: () => AssistantMessage.ClickedOpen() },
        }),
      h.section
        .attrs({
          "aria-label": "Assistant",
          hidden: open ? undefined : "",
          class: cn(DOCK, open ? DOCKED : MINIMIZED),
        })
        .on("keydown", ({ key }) => (key === "Escape" ? AssistantMessage.PressedEscape() : undefined))
        .children(
          h.header.class("flex items-center justify-between gap-3 border-b border-border py-1.5 pr-1.5 pl-4").children(
            h.span.class("flex min-w-0 items-center gap-2").children(
              Icon(h, "sparkles", {
                class: "size-3.5 shrink-0 text-primary",
              }),
              Label(h).children("Assistant"),
              target && h.span.class("truncate text-[12px] text-muted-foreground").children(target.league.name),
            ),
            h.span.class("flex shrink-0 items-center").children(
              IconButton(h, {
                key: "new",
                props: {
                  label: "New conversation",
                  side: "bottom",
                  icon: "rotate-ccw",
                  disabled: target === null,
                },
                onEmit: {
                  Clicked: () => AssistantMessage.ClickedNewConversation(),
                },
              }),
              IconButton(h, {
                key: "minimize",
                props: { label: "Minimize", side: "bottom", icon: "minus" },
                onEmit: { Clicked: () => AssistantMessage.ClickedMinimize() },
              }),
            ),
          ),
          Context(h, shown),
          h.div.class("min-h-0 flex-1 overflow-y-auto p-4").children(
            target === null
              ? h.p
                  .class("text-[13px] leading-relaxed text-muted-foreground")
                  .children("Open a league to ask about it.")
              : (model.started || open) &&
                  AssistantChat(h, {
                    key: `${target.competition.key}:${target.league.league_id}:${model.generation}`,
                    props: {
                      competition: target.competition.key,
                      league: target.league.league_id,
                      generation: model.generation,
                      onScreen: shown.map((s) => s.subject),
                      asked,
                      placeholder: "Ask about this page",
                      empty: "Ask about anything on screen.",
                    },
                    onEmit: {
                      TookAsked: () => AssistantMessage.TookChatAsked(),
                    },
                  }),
          ),
        ),
    );
  },
});

/**
 * What the assistant can see, under its header.
 *
 * Said rather than implied: an answer about the wrong page is a mystery
 * unless you can see what the question was asked with.
 */
function Context<M>(h: Html.H<M>, shown: readonly Shown[]) {
  return h.p
    .class(
      "flex items-center gap-1.5 border-b border-border/45 px-4 py-1.5 font-mono text-[11px] text-muted-foreground",
    )
    .children(
      Icon(h, "eye", { class: "size-3 shrink-0" }),
      h.span.class("truncate").children(shown.length ? shown.map((s) => s.label).join(" · ") : "No league open"),
    );
}
