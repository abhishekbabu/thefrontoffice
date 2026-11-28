/**
 * A page's drawers, and the one piece of state that opens them: a player,
 * players side by side, or a league move.
 *
 * One shows at a time. Opening a player from a comparison swaps the
 * comparison out, and his drawer's Back link brings it back; a comparison or
 * a player opened from a move does the same for the move, and a move opened
 * from a player's history for the player. Where to go back to is data — the
 * drawer it replaced, held in `back` — so a page keeps it in its Model like
 * any other value, and it survives a reload of the history entry.
 *
 * Every table in the app opens a player, and each panel was wiring the same
 * things by hand: a nullable id, the way to set it, and a drawer whose props
 * were identical everywhere. Forgetting the closing half leaves a drawer that
 * opens and never shuts, which is exactly the kind of mistake a repeated block
 * invites. So the page holds only `drawer: Schema.NullOr(DrawerState)`, sets
 * it from `RequestedOpen` and clears it on `RequestedClose`; everything that
 * moves between drawers happens in here.
 */
import { Subscription, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Schema, Stream } from "effect";
import { Comparing, ComparisonDrawer } from "@/components/league/compare";
import { MoveDrawer, moveLabel } from "@/components/league/move";
import { PlayerDrawer } from "@/components/league/player";
import type { ActivityRow } from "@/lib/types";
import { wire } from "@/lib/wire";

/** Where a drawer was opened from, to return to: what its Back link says, and the drawer it reopens. */
interface Back {
  readonly label: string;
  readonly open: DrawerState;
}

/**
 * Which drawer is open, and the one it replaced.
 *
 * `own` is a drawer the page draws itself (the Fixtures page's game): nothing
 * is drawn for it here, but a player opened from it can go back to it, which
 * reaches the page as a `RequestedOpen` of it like any other.
 */
export type DrawerState =
  | { readonly kind: "player"; readonly id: string; readonly back: Back | null }
  | {
      readonly kind: "compare";
      readonly ids: readonly string[];
      readonly title?: string | undefined;
      readonly tags?: { readonly [id: string]: string } | undefined;
      readonly back: Back | null;
    }
  | { readonly kind: "move"; readonly move: ActivityRow; readonly back: Back | null }
  | { readonly kind: "own"; readonly key: string; readonly back: Back | null };

const BackOf: Schema.Codec<Back> = Schema.Struct({
  label: Schema.String,
  open: Schema.suspend((): Schema.Codec<DrawerState> => DrawerState),
});

const back = Schema.NullOr(BackOf);

export const DrawerState: Schema.Codec<DrawerState> = Schema.Union([
  Schema.Struct({ kind: Schema.Literal("player"), id: Schema.String, back }),
  Schema.Struct({ kind: Schema.Literal("compare"), ...Comparing.fields, back }),
  Schema.Struct({ kind: Schema.Literal("move"), move: wire<ActivityRow>(), back }),
  Schema.Struct({ kind: Schema.Literal("own"), key: Schema.String, back }),
]);

/** A player's drawer, opened from the page. */
export const playerDrawer = (id: string): DrawerState => ({ kind: "player", id, back: null });

/**
 * Players side by side, opened from the page, headed as `heading` says
 * (`Comparing`). One player is no comparison: he opens in his own drawer.
 */
export function comparisonDrawer(
  ids: readonly string[],
  heading: { title?: string | undefined; tags?: Comparing["tags"] } = {},
): DrawerState {
  const [only] = ids;

  if (ids.length === 1 && only !== undefined) return playerDrawer(only);

  return { kind: "compare", ids: [...ids], title: heading.title, tags: heading.tags, back: null };
}

/** A league move in full, opened from the page: the Activity page's rows. */
export const moveDrawer = (move: ActivityRow): DrawerState => ({ kind: "move", move, back: null });

/** `open`, reached from the drawer `from` and named `label` on its way back there. */
const from = (open: DrawerState, label: string, current: DrawerState): DrawerState => ({
  ...open,
  back: { label, open: current },
});

/**
 * Whether two drawers are the same one. Both are plain data the page holds
 * and hands back, so their JSON says it.
 */
const same = (a: DrawerState | null, b: DrawerState | null) => JSON.stringify(a) === JSON.stringify(b);

const Swapped = Schema.Struct({ to: DrawerState, swap: Schema.Literals(["forward", "back"]) });

const DrawersEvents = UiSchema.TaggedEnum({
  RequestedOpen: { open: DrawerState },
  RequestedClose: {},
});

const DrawersMessage = UiSchema.TaggedEnum({
  /** A drawer is showing: what to keep on screen while it slides out. */
  ShowedDrawer: { open: DrawerState },
  RequestedClosePlayer: {},
  RequestedBackPlayer: {},
  RequestedOpenPlayerMove: { move: wire<ActivityRow>(), label: Schema.String },
  RequestedCloseComparison: {},
  RequestedBackComparison: {},
  RequestedOpenComparisonPlayer: { id: Schema.String, label: Schema.String },
  RequestedCloseMove: {},
  ClickedBackMove: {},
  ClickedMovePlayer: { id: Schema.String },
  ClickedCompareMove: { ids: Schema.Array(Schema.String) },
});

export const Drawers = Html.component({
  name: "Drawers",
  props: Schema.Struct({ competition: Schema.String, league: Schema.String, open: Schema.NullOr(DrawerState) }),
  model: Schema.Struct({
    /**
     * What each drawer last showed, so it still has someone to show on the
     * way out: reading `open` alone would blank it for the length of the slide.
     */
    kept: Schema.Struct({
      player: Schema.String,
      comparing: Schema.NullOr(Comparing),
      move: Schema.NullOr(wire<ActivityRow>()),
    }),
    /**
     * The last move between drawers made from in here, and which way. Only
     * while the page shows exactly that drawer does it swap rather than slide:
     * one the page opened itself crosses from the screen's edge.
     */
    moved: Schema.NullOr(Swapped),
  }),
  message: DrawersMessage,
  events: DrawersEvents,
  restore: false,
}).make({
  init: () => ({ kept: { player: "", comparing: null, move: null }, moved: null }),
  update: ($, message) => {
    const current = $.props.open;
    const close = () => $.evolve({ moved: null }).emit(DrawersEvents.RequestedClose());

    const go = (to: DrawerState, swap: "forward" | "back") =>
      $.evolve({ moved: { to, swap } }).emit(DrawersEvents.RequestedOpen({ open: to }));

    const goBack = () => (current?.back ? go(current.back.open, "back") : $.model);
    const goOn = (to: DrawerState, label: string) => (current === null ? $.model : go(from(to, label, current), "forward"));

    return DrawersMessage.match(message, {
      ShowedDrawer: ({ open }) => {
        switch (open.kind) {
          case "player":
            return $.evolve({ kept: (kept) => ({ ...kept, player: open.id }) });
          case "compare":
            return $.evolve({ kept: (kept) => ({ ...kept, comparing: { ids: open.ids, title: open.title, tags: open.tags } }) });
          case "move":
            return $.evolve({ kept: (kept) => ({ ...kept, move: open.move }) });
          case "own":
            return $.model;
        }
      },
      RequestedClosePlayer: close,
      RequestedCloseComparison: close,
      RequestedCloseMove: close,
      RequestedBackPlayer: goBack,
      RequestedBackComparison: goBack,
      ClickedBackMove: goBack,
      RequestedOpenPlayerMove: ({ move, label }) => goOn(moveDrawer(move), label),
      RequestedOpenComparisonPlayer: ({ id, label }) => goOn(playerDrawer(id), label),
      ClickedMovePlayer: ({ id }) =>
        current?.kind === "move" ? goOn(playerDrawer(id), moveLabel(current.move)) : $.model,
      ClickedCompareMove: ({ ids }) =>
        current?.kind === "move" ? goOn(comparisonDrawer(ids), moveLabel(current.move)) : $.model,
    });
  },
  // Keyed by the whole drawer, so each one opened is kept once.
  subscriptions: ($) => {
    const open = $.props.open;

    return open === null
      ? []
      : [Subscription.make("showed", JSON.stringify(open), () => Stream.make(DrawersMessage.ShowedDrawer({ open })))];
  },
  view: (h, model) => {
    const { competition, league, open } = h.props;
    const backLabel = open?.back?.label ?? null;
    const swap = model.moved !== null && same(model.moved.to, open) ? model.moved.swap : null;

    return h.div.class("contents").children(
      PlayerDrawer(h, {
        props: {
          competition,
          league,
          player: open?.kind === "player" ? open.id : model.kept.player,
          open: open?.kind === "player",
          back: open?.kind === "player" ? backLabel : null,
          swap,
        },
        onEmit: {
          RequestedClose: () => DrawersMessage.RequestedClosePlayer(),
          RequestedBack: () => DrawersMessage.RequestedBackPlayer(),
          RequestedOpenMove: ({ move, label }) => DrawersMessage.RequestedOpenPlayerMove({ move, label }),
        },
      }),
      ComparisonDrawer(h, {
        props: {
          competition,
          league,
          comparing: open?.kind === "compare" ? { ids: open.ids, title: open.title, tags: open.tags } : model.kept.comparing,
          open: open?.kind === "compare",
          back: open?.kind === "compare" ? backLabel : null,
          swap,
        },
        onEmit: {
          RequestedClose: () => DrawersMessage.RequestedCloseComparison(),
          RequestedBack: () => DrawersMessage.RequestedBackComparison(),
          RequestedOpenPlayer: ({ id, label }) => DrawersMessage.RequestedOpenComparisonPlayer({ id, label }),
        },
      }),
      MoveDrawer(h, {
        move: open?.kind === "move" ? open.move : model.kept.move,
        open: open?.kind === "move",
        back: open?.kind === "move" && backLabel !== null ? { label: backLabel, onBack: DrawersMessage.ClickedBackMove() } : undefined,
        swap,
        onClose: DrawersMessage.RequestedCloseMove(),
        onOpenPlayer: (id) => DrawersMessage.ClickedMovePlayer({ id }),
        onCompare: (ids) => DrawersMessage.ClickedCompareMove({ ids }),
      }),
    );
  },
});
