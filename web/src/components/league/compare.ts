import { Command, Router, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Option, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { CompareProvider, CompareProviderMessage } from "@/components/league/compare-provider";
import { Chips, Portrait } from "@/components/league/player-parts";
import { Card } from "@/components/ui/card";
import { IconButton } from "@/components/ui/controls/icon-button";
import { Icon } from "@/components/ui/icon";
import { LABEL, Meta } from "@/components/ui/label";
import { SlideOver, SlideOverHeader, Swap } from "@/components/ui/overlays/dialog";
import { QueryState } from "@/components/ui/state";
import { Table, Td, Th } from "@/components/ui/table";
import { MAX_COMPARED, scopeOf } from "@/lib/compare";
import { compareLabel, sides } from "@/lib/comparing";
import { GetComparison } from "@/lib/queries/players";
import { AppRoute } from "@/lib/route";
import type { PlayerComparison } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * What a comparison is opened with: whom, and how to head it (`lib/comparing.ts`).
 *
 * `tags` names each player's side where the comparison came from a decision —
 * "In" and "Out" on a to-do, "Give" and "Get" on a trade — so a column says
 * which way he goes before it says anything else.
 */
export const Comparing = Schema.Struct({
  ids: Schema.Array(Schema.String),
  title: Schema.optional(Schema.String),
  tags: Schema.optional(Schema.Record(Schema.String, Schema.String)),
});

export type Comparing = typeof Comparing.Type;

/**
 * The comparison itself: a column per player and a row per measure, one
 * section per heading, the best of each row marked.
 *
 * Every competition's comparison is built by the server from what each
 * player's drawer shows, so this reads the same for a quarterback, a centre
 * and a goalkeeper; the Compare page and the drawer both draw it.
 */
export function ComparisonGrid<M>(
  h: Html.H<M>,
  {
    comparison,
    tags,
    onOpen,
    onRemove,
  }: {
    comparison: PlayerComparison;
    tags?: Comparing["tags"];
    onOpen: (id: string) => M;
    /** Where the list can be changed: the Compare page, not a decision's drawer. */
    onRemove?: ((id: string) => M) | undefined;
  },
) {
  const { players, tables } = comparison;

  return Table(h).children(
    h.thead.children(
      h.tr.children(
        Th(h),
        players.map((p) =>
          Th(h, "min-w-28 normal-case tracking-normal sm:min-w-40")
            .key(p.player_id)
            .children(
              h.div.class("flex items-start justify-between gap-2").children(
                // Off on a phone: two players and their labels fit the width only without them.
                h.div
                  .class("hidden sm:block")
                  .children(Portrait(h, { key: `portrait-${p.player_id}`, src: p.image_url, class: "size-14" })),
                h.button
                  .attrs({ type: "button", class: "min-w-0 flex-1 text-left" })
                  .on("click", onOpen(p.player_id))
                  .on("keydown", () => undefined)
                  .children(
                    tags?.[p.player_id] && h.span.attr("class", cn(LABEL, "block")).children(tags[p.player_id] ?? ""),
                    h.div.class("truncate font-sans text-[13.5px] font-semibold text-foreground").children(p.name),
                    Meta(h, { as: "div", class: "font-normal" }).children([p.position, p.team].filter(Boolean).join(" · ")),
                    p.headline &&
                      h.div
                        .class("mt-1 font-mono text-[15px] font-semibold text-foreground tabular-nums")
                        .children(p.headline),
                  ),
                onRemove &&
                  IconButton(h, {
                    key: `remove-${p.player_id}`,
                    props: { label: `Remove ${p.name}`, icon: "x" },
                    onEmit: { Clicked: () => onRemove(p.player_id) },
                  }),
              ),
              Chips(h, { detail: p, class: "mt-1" }),
            ),
        ),
      ),
    ),
    tables.map((table) =>
      h.tbody.key(table.title).children(
        // The heading once, over its rows, rather than as a prefix on every label.
        h.tr.children(
          h.th
            .attrs({
              scope: "colgroup",
              colspan: String(players.length + 1),
              class: cn(LABEL, "border-b border-border bg-muted px-4 py-1.5 text-left"),
            })
            .children(table.title),
        ),
        table.rows.map((row) =>
          h.tr.key(row.label).children(
            // Wraps rather than widening its column: a label naming who is out
            // ("Without Jalen Williams (O, back ~2 Mar), …") would push
            // the players off the side of a drawer.
            Td(h, "w-[30%] min-w-28 text-muted-foreground").children(row.label),
            row.values.map((value, i) =>
              Cell(h, { value, absent: value === table.absent, best: row.best.includes(i) }).key(`${row.label}-${i}`),
            ),
          ),
        ),
      ),
    ),
  );
}

/** One figure; the best of its row is set heavier, in the good color, and starred, so it reads without color too. */
function Cell<M>(h: Html.H<M>, { value, absent, best }: { value: string; absent: boolean; best: boolean }) {
  return Td(h, cn("font-mono text-[12.5px]", absent && "text-muted-foreground/50", best && "font-semibold text-ok")).children(
    h.span.class("inline-flex items-center gap-1").children(
      value,
      best && Icon(h, "star", { class: "size-3 fill-current" }),
      best && h.span.class("sr-only").children("best"),
    ),
  );
}

export const ComparisonDrawerEvents = UiSchema.TaggedEnum({
  RequestedClose: {},
  /** Back to the drawer this one replaced. */
  RequestedBack: {},
  /** One of the players, to open in this drawer's place; `label` names this comparison for his Back link. */
  RequestedOpenPlayer: { id: Schema.String, label: Schema.String },
});

const ComparisonDrawerMessage = UiSchema.TaggedEnum({
  RequestedCloseDrawer: {},
  ClickedBack: {},
  ClickedComparePage: {},
  ClickedPlayer: { id: Schema.String },
});

const answered = (result: AsyncResult.AsyncResult<PlayerComparison, unknown>) =>
  Option.getOrUndefined(AsyncResult.value(result));

/**
 * A comparison in a drawer, over whatever it was opened from: the players a
 * to-do weighs, a trade's two sides, a move's players. The Compare page is
 * the same grid kept across visits; this one is about the decision in front
 * of you, and can be carried over to that page.
 *
 * `comparing` is what it shows, kept by the caller while it slides out;
 * `open` false is the closed state.
 */
export const ComparisonDrawer = Html.component({
  name: "ComparisonDrawer",
  props: Schema.Struct({
    competition: Schema.String,
    league: Schema.String,
    comparing: Schema.NullOr(Comparing),
    open: Schema.Boolean,
    /** What its Back link names: the drawer it replaced, or null where it replaced none. */
    back: Schema.NullOr(Schema.String),
    swap: Swap,
  }),
  model: Schema.Null,
  message: ComparisonDrawerMessage,
  events: ComparisonDrawerEvents,
  // Read only so that its send is optional: a drawer with no list to carry over to still opens.
  reads: { compare: { owner: CompareProvider, optional: true } },
  queries: {
    comparison: {
      query: GetComparison,
      args: ({ props }) => {
        const ids = (props.comparing?.ids ?? []).slice(0, MAX_COMPARED);

        return ids.length ? { competition: props.competition, league: props.league, ids } : undefined;
      },
    },
  },
}).make({
  init: () => null,
  update: {
    RequestedCloseDrawer: ($) => $.emit(ComparisonDrawerEvents.RequestedClose()),
    ClickedBack: ($) => $.emit(ComparisonDrawerEvents.RequestedBack()),
    ClickedPlayer: ($, { id }) =>
      $.emit(
        ComparisonDrawerEvents.RequestedOpenPlayer({ id, label: `Compare · ${compareLabel(answered($.queries.comparison), "Players")}` }),
      ),
    // Carried over as the Compare page's list, which replaces whatever it held.
    ClickedComparePage: ($) => {
      const { competition, league } = $.props;
      const ids = ($.props.comparing?.ids ?? []).slice(0, MAX_COMPARED);

      return $.send(CompareProvider, CompareProviderMessage.RequestedSet({ scope: scopeOf(competition, league), ids }))
        .emit(ComparisonDrawerEvents.RequestedClose())
        .run(
          Router.push(AppRoute, AppRoute.View({ params: { competition, league, view: "compare" } })).pipe(Command.asNoop),
        );
    },
  },
  view: (h) => {
    const { comparing, open, back, swap } = h.props;
    const shown = comparing ?? { ids: [] };
    const ids = shown.ids.slice(0, MAX_COMPARED);
    const comparison = answered(h.queries.comparison);
    const names = compareLabel(comparison, "Players");

    return SlideOver(h, {
      key: "compare",
      open: open && comparing !== null,
      onClose: ComparisonDrawerMessage.RequestedCloseDrawer(),
      label: `Compare ${names}`,
      swap,
      // A column per player: two read in the player drawer's width, three or four need more.
      class: cn("border-l border-border", ids.length > 2 ? "max-w-4xl" : "max-w-2xl"),
      children: [
        SlideOverHeader(h, {
          title: [shown.title ?? names],
          meta: shown.title ? sides(comparison, shown.tags) || names : `${ids.length} players`,
          back: back === null ? undefined : { label: back, onBack: ComparisonDrawerMessage.ClickedBack() },
          onClose: ComparisonDrawerMessage.RequestedCloseDrawer(),
          children: [
            IconButton(h, {
              key: "compare-page",
              props: { label: "Open on the Compare page", icon: "maximize-2" },
              onEmit: { Clicked: () => ComparisonDrawerMessage.ClickedComparePage() },
            }),
          ],
        }),
        h.div.class("flex flex-col gap-4 p-5").children(
          QueryState(h, h.queries.comparison, { lines: 6 }),
          comparison &&
            Card(h, "overflow-x-auto").children(
              ComparisonGrid(h, { comparison, tags: shown.tags, onOpen: (id) => ComparisonDrawerMessage.ClickedPlayer({ id }) }),
            ),
        ),
      ],
    });
  },
});
