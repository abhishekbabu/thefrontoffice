/**
 * One player, opened from wherever their name appears.
 *
 * A panel rather than a page: you open it to settle a question about a row you
 * are already looking at, and closing it should put you back exactly there.
 * Where it was opened from, and where its moves and comparisons go, is the
 * page's drawers' (`components/league/drawers.ts`): this draws one player and
 * says what was asked of it.
 */
import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Option, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { AssistantProvider } from "@/components/league/assistant-provider";
import { CompareProvider, CompareProviderMessage } from "@/components/league/compare-provider";
import { MoveRow } from "@/components/league/move";
import { Headlines, Portrait, TableOfStats, TeamLine, facts } from "@/components/league/player-parts";
import { UntouchableToggle } from "@/components/league/untouchable";
import { Badge } from "@/components/ui/badge";
import { ExternalLink } from "@/components/ui/controls/external-link";
import { IconButton } from "@/components/ui/controls/icon-button";
import { MARKER, Tabs } from "@/components/ui/controls/tabs";
import { Label } from "@/components/ui/label";
import { ListCard } from "@/components/ui/list";
import { BackLink, SlideOver, Swap } from "@/components/ui/overlays/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { StatCells, StatList } from "@/components/ui/stat";
import { Empty, QueryState } from "@/components/ui/state";
import { MAX_COMPARED, scopeOf } from "@/lib/compare";
import { GetPlayer, GetPlayerTab } from "@/lib/queries/players";
import { Shown } from "@/lib/screen";
import type { ActivityRow, PlayerDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { wire } from "@/lib/wire";

/**
 * Which of his tabs to offer, which is shown, and which of them is read on its own.
 *
 * Each section is in its tab: one with none of its own sits in the first. A
 * tab with nothing in it is not offered, and with one tab there is no bar. A
 * deferred tab is offered before anyone knows what it holds: it is read only
 * once opened, since each costs a request the first tab does not.
 */
function layout(detail: PlayerDetail | undefined, tab: string) {
  const tabOf = (section: { tab: string }) => section.tab || detail?.tabs[0] || "";
  const filled = detail ? detail.groups.filter((group) => group.stats.length > 0) : [];
  const movesTab = detail ? detail.moves_tab || detail.tabs[0] || "" : "";
  const deferred = detail?.deferred ?? [];

  const present = (detail?.tabs ?? []).filter(
    (t) =>
      deferred.includes(t) ||
      filled.some((g) => tabOf(g) === t) ||
      detail?.tables.some((x) => tabOf(x) === t) ||
      (t === movesTab && (detail?.moves.length ?? 0) > 0),
  );

  const current = present.includes(tab) ? tab : present[0];
  const opened = current && deferred.includes(current) ? current : "";
  const shownHere = (section: { tab: string }) => present.length <= 1 || tabOf(section) === current;

  return { present, current, opened, movesTab, shownHere };
}

/** What a query holds once it has answered: its value, or nothing yet. */
const answered = <A, E>(result: AsyncResult.AsyncResult<A, E>): A | undefined =>
  Option.getOrUndefined(AsyncResult.value(result));

/**
 * Tells the assistant what is on screen, for as long as it is drawn: a
 * question to the assistant docked over the drawer is about him. Its own
 * component because a report is read from props, and his name is the
 * drawer's query's, not its Model's.
 */
const OnScreen = Html.component({
  name: "OnScreen",
  props: Schema.Struct({ shown: Shown }),
  model: Schema.Null,
  message: Schema.Never,
  reads: { assistant: { owner: AssistantProvider, optional: true, report: (_model, props) => props.shown } },
}).make({ init: () => null, update: ($) => $.model, view: (h) => h.span.class("hidden") });

export const PlayerDrawerEvents = UiSchema.TaggedEnum({
  RequestedClose: {},
  /** Back to the drawer this one replaced. */
  RequestedBack: {},
  /** One of the moves on his history, to open in this drawer's place; `label` is his name, for its Back link. */
  RequestedOpenMove: { move: wire<ActivityRow>(), label: Schema.String },
});

const PlayerDrawerMessage = UiSchema.TaggedEnum({
  PickedTab: { tab: Schema.String },
  RequestedCloseDrawer: {},
  ClickedBack: {},
  ClickedCompare: {},
  ClickedMove: { move: wire<ActivityRow>() },
});

/**
 * His drawer. `player` is who it shows — the caller keeps him while the
 * drawer slides out, since reading the open state alone would blank the
 * contents for the length of the slide — and `open` false is the closed state.
 */
export const PlayerDrawer = Html.component({
  name: "PlayerDrawer",
  props: Schema.Struct({
    competition: Schema.String,
    league: Schema.String,
    player: Schema.String,
    open: Schema.Boolean,
    /** What his Back link names: the drawer he replaced, or null where he replaced none. */
    back: Schema.NullOr(Schema.String),
    swap: Swap,
  }),
  model: Schema.Struct({ tab: Schema.String }),
  message: PlayerDrawerMessage,
  events: PlayerDrawerEvents,
  reads: { compare: { owner: CompareProvider, optional: true } },
  queries: {
    player: {
      query: GetPlayer,
      // Never another player's answer under this one's name.
      dropPrevious: true,
      args: ({ props }) =>
        props.player === "" ? undefined : { competition: props.competition, league: props.league, player: props.player },
    },
    part: {
      query: GetPlayerTab,
      dropPrevious: true,
      args: ({ props, model, queries }) => {
        const { opened } = layout(answered(queries.player), model.tab);

        return props.player === "" || opened === ""
          ? undefined
          : { competition: props.competition, league: props.league, player: props.player, tab: opened };
      },
    },
  },
  restore: false,
}).make({
  init: () => ({ tab: "" }),
  update: {
    PickedTab: ($, { tab }) => $.evolve({ tab }).viewTransition([MARKER]),
    RequestedCloseDrawer: ($) => $.emit(PlayerDrawerEvents.RequestedClose()),
    ClickedBack: ($) => $.emit(PlayerDrawerEvents.RequestedBack()),
    ClickedCompare: ($) => {
      const scope = scopeOf($.props.competition, $.props.league);
      const id = $.props.player;

      return ($.reads.compare?.[scope] ?? []).includes(id)
        ? $.send(CompareProvider, CompareProviderMessage.RequestedRemove({ scope, id }))
        : $.send(CompareProvider, CompareProviderMessage.RequestedAdd({ scope, id }));
    },
    ClickedMove: ($, { move }) =>
      $.emit(PlayerDrawerEvents.RequestedOpenMove({ move, label: answered($.queries.player)?.name ?? "Player" })),
  },
  view: (h, model) => {
    const { competition, league, player: id, open, back, swap } = h.props;
    const detail = answered(h.queries.player);
    const { present, current, opened, movesTab, shownHere } = layout(detail, model.tab);
    const source = opened ? answered(h.queries.part) : detail;
    const tables = (source?.tables ?? []).filter(shownHere);
    const groups = (source?.groups ?? []).filter((group) => group.stats.length > 0).filter(shownHere);
    const moves = source && shownHere({ tab: movesTab }) ? source.moves : [];
    const nothing = Boolean(opened && source && !tables.length && !groups.length && !moves.length);
    const shownFacts = detail ? facts(detail) : [];
    const compared = h.reads.compare?.[scopeOf(competition, league)] ?? [];
    const has = compared.includes(id);
    const full = compared.length >= MAX_COMPARED;

    return SlideOver(h, {
      key: "player",
      open,
      onClose: PlayerDrawerMessage.RequestedCloseDrawer(),
      label: detail?.name ?? "Player",
      swap,
      // Wide enough that a season table fits without scrolling inside
      // itself — three columns of "£14.0m → £14.7m" is what sets the
      // floor. Still capped, and still full width on a narrow screen.
      class: "max-w-2xl border-l border-border",
      children: [
        // Everything that says who this is, pinned. On a long stat table
        // the name and the one figure they are judged on are exactly what
        // you stop being able to see, and they are what every row below is
        // about.
        h.div.class("sticky top-0 z-10 border-b border-border bg-popover").children(
          back !== null &&
            h.div.class("px-5 pt-3").children(BackLink(h, { label: back, onBack: PlayerDrawerMessage.ClickedBack() })),
          h.div.class("flex items-start gap-4 px-5 py-3.5").children(
            detail && Portrait(h, { key: "portrait", src: detail.image_url }),
            h.div.class("min-w-0 flex-1").children(
              detail
                ? h.div.class("contents").children(
                    h.h2.class("font-display text-[21px] font-semibold leading-tight tracking-tight").children(detail.name),
                    TeamLine(h, detail),
                    detail.note &&
                      // Wraps rather than running off the drawer: FPL's news is a sentence.
                      Badge(h, {
                        variant: "warn",
                        appearance: "status",
                        class:
                          "mt-1.5 h-auto min-h-5 max-w-full items-start whitespace-normal rounded-md py-[3px] leading-snug before:mt-[3.5px]",
                      }).children(detail.note),
                    // No figure to lead with: why not, as a sentence rather than a blank cell.
                    !detail.headline &&
                      detail.headline_label &&
                      h.p.class("mt-1 text-[12.5px] leading-snug text-muted-foreground").children(detail.headline_label),
                  )
                : h.div.class("flex flex-col gap-2 pt-0.5").children(Skeleton(h, "h-5 w-44"), Skeleton(h, "h-3 w-24")),
            ),
            h.div.class("flex shrink-0 items-center").children(
              detail &&
                IconButton(h, {
                  key: "compare",
                  props: {
                    label: has ? "Remove from compare" : full ? `Compare holds ${MAX_COMPARED}` : "Add to compare",
                    icon: "git-compare-arrows",
                    pressed: has,
                    disabled: !has && full,
                  },
                  onEmit: { Clicked: () => PlayerDrawerMessage.ClickedCompare() },
                }),
              detail && UntouchableToggle(h, { key: "untouchable", props: { competition, league, player: id } }),
              detail?.url &&
                ExternalLink(h, { key: "platform", props: { href: detail.url, label: `Open ${detail.name} on the platform` } }),
              IconButton(h, {
                key: "close",
                props: { label: "Close", side: "left", icon: "x" },
                onEmit: { Clicked: () => PlayerDrawerMessage.RequestedCloseDrawer() },
              }),
            ),
          ),
          shownFacts.length > 0 && StatCells(h, { stats: shownFacts, class: "border-t border-border" }),
          present.length > 1 &&
            Tabs(h, {
              group: "player",
              tabs: present.map((t) => ({ id: t, label: t })),
              current,
              onPick: (tab) => PlayerDrawerMessage.PickedTab({ tab }),
              class: cn("px-5 pb-2", shownFacts.length > 0 && "border-t border-border pt-2"),
            }),
        ),

        QueryState(h, h.queries.player, { lines: 4 }),
        opened && QueryState(h, h.queries.part, { lines: 4, class: "mx-5 mt-4" }),
        nothing && Empty(h, { title: `No ${opened.toLowerCase()} on record.` }),

        detail &&
          // Room at the foot for the assistant's button, which sits over the
          // drawer. Keyed by the tab, so its sections arrive again on a new one.
          h.div
            .key(`${detail.player_id}-${current ?? ""}`)
            .class("flex flex-col gap-5 px-5 pt-4 pb-20")
            .children(
              // Now before then: his form, status and outlook, and only after
              // them the seasons behind him. A group with nothing in it is a
              // heading that says nothing — a kicker has no passing line, and
              // "Projected line" over empty space reads as a figure that failed
              // to arrive.
              groups.map((group) =>
                h.section
                  .key(`group-${group.title}`)
                  .class("animate-list-item")
                  .children(
                    Label(h, { as: "h3", class: "mb-1.5 block" }).children(group.title),
                    group.stats.every((stat) => stat.url)
                      ? Headlines(h, group.stats)
                      : StatList(h, { stats: group.stats }),
                  ),
              ),
              tables.map((table) =>
                h.section
                  .key(`table-${table.title}`)
                  .class("animate-list-item")
                  .children(Label(h, { as: "h3", class: "mb-1.5 block" }).children(table.title), TableOfStats(h, table)),
              ),
              moves.length > 0 &&
                // The league's own rows: one opens the move as Activity does.
                h.section.key("moves").class("animate-list-item").children(
                  ListCard(h, {
                    title: "Moves",
                    count: `${moves.length}`,
                    children: moves.map((row, i) =>
                      MoveRow(h, { move: row, onOpen: PlayerDrawerMessage.ClickedMove({ move: row }) }).key(`${row.when}-${i}`),
                    ),
                  }),
                ),
            ),

        open &&
          detail &&
          OnScreen(h, { key: "shown", props: { shown: { subject: { kind: "player", key: detail.player_id }, label: detail.name } } }),
      ],
    });
  },
});
