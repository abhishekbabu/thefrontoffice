import { Component, Command, UiSchema } from "@effect/ui";
import type { View } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Effect, Schema } from "effect";
import { ExternalLink } from "@/components/ui/controls/external-link";
import { IconButton } from "@/components/ui/controls/icon-button";
import { ApiError, api } from "@/lib/api";
import { ListLeagues } from "@/lib/queries/app";
import { fetching, tags } from "@/lib/queries/cache";
import type { Competition, League } from "@/lib/types";

/**
 * The bar that says where you are and what you can do from here.
 *
 * Pinned, because both halves stay relevant the whole way down a page: on a
 * long one the title is what a figure belongs to, and the controls are the way
 * out. Opaque rather than translucent — content scrolling visibly underneath
 * a title reads as two pages at once.
 *
 * `leading` sits before the title, which is where a control that leaves the
 * page belongs: back is upstream of where you are, and reads that way to the
 * left of the name of it.
 */
export function PageHeader<M, L extends View.Children<M> = [], C extends View.Children<M> = []>(
  h: Html.H<M>,
  {
    title,
    meta,
    leading,
    href,
    hrefLabel,
    children,
  }: {
    title: string;
    meta?: string | undefined;
    leading?: L | undefined;
    /** The platform this thing lives on, opened in a new tab. */
    href?: string | undefined;
    hrefLabel?: string | undefined;
    children?: C | undefined;
  },
) {
  // The bar spans the column; what is in it keeps to the page's width
  // (`--page-max`), so the controls sit over the content they act on rather
  // than at the far edge of a wide screen.
  return h.header.attrs({ "data-bleed": "", class: "sticky top-0 z-20 border-b border-border bg-background" }).children(
    h.div.class("flex mx-auto max-w-(--page-max) flex-wrap items-center justify-between gap-3 px-5 py-4").children(
      h.div.class("flex min-w-0 items-center gap-3").children(
        leading,
        h.div.class("min-w-0").children(
          // On the name's own line rather than after the block: the meta line
          // is much the longer of the two, so a link placed after both drifts
          // out to the far right and stops reading as belonging to the name.
          h.div.class("flex min-w-0 items-center gap-1").children(
            h.h1.class("truncate font-display text-[21px] font-semibold leading-tight tracking-tight").children(title),
            href &&
              ExternalLink(h, {
                key: "platform",
                props: { href, label: hrefLabel ?? "Open on the platform", class: "h-6 shrink-0 px-1" },
              }),
          ),
          meta && h.p.class("mt-0.5 font-mono text-[12px] text-muted-foreground").children(meta),
        ),
      ),
      children,
    ),
  );
}

const RefreshMessage = UiSchema.TaggedEnum({
  ClickedRefresh: {},
  SucceededRefreshLeague: {},
  FailedRefreshLeague: { message: Schema.String },
});

/**
 * Reads the league from its platform again, rather than from what the server
 * keeps of it: right after a move, a kept roster is an hour behind it.
 *
 * Every answer about the league goes stale with it, and so does the league
 * list, which carries the week being played.
 */
class RefreshLeague extends Command.Service<RefreshLeague>()("league/RefreshLeague", {
  args: { competition: Schema.String, league: Schema.String },
  success: RefreshMessage,
  invalidates: () => [tags.league, ListLeagues],
}) {
  static readonly layer = this.toLayer(({ competition, league }) =>
    fetching(() => api.league(competition, league).refresh()).pipe(
      Effect.match({
        onSuccess: () => RefreshMessage.SucceededRefreshLeague(),
        onFailure: (error: ApiError) => RefreshMessage.FailedRefreshLeague({ message: error.message }),
      }),
    ),
  );
}

const RefreshNoDeps = Html.component({
  name: "Refresh",
  props: Schema.Struct({ competition: Schema.String, league: Schema.String }),
  model: Schema.Struct({ failed: Schema.NullOr(Schema.String) }),
  message: RefreshMessage,
}).make({
  init: () => ({ failed: null }),
  update: {
    ClickedRefresh: ($) =>
      $.evolve({ failed: null }).run(RefreshLeague.make({ competition: $.props.competition, league: $.props.league })),
    SucceededRefreshLeague: ($) => $.evolve({ failed: null }),
    FailedRefreshLeague: ($, { message }) => $.evolve({ failed: message }),
  },
  view: (h, model) => {
    const pending = h.isRunning(RefreshLeague);

    return IconButton(h, {
      key: "refresh",
      props: {
        label: model.failed === null ? "Refresh" : `Refresh failed: ${model.failed}`,
        icon: "rotate-cw",
        iconClass: pending ? "motion-safe:animate-spin" : undefined,
        disabled: pending,
      },
      onEmit: { Clicked: () => RefreshMessage.ClickedRefresh() },
    });
  },
});

const Refresh = RefreshNoDeps.pipe(Component.provide(RefreshLeague.layer));

/**
 * The header for a page about a league, which is most of them.
 *
 * Four panels set the same four props, and each spelled the link's label out
 * again — so the one sentence a screen reader hears for "open this on the
 * platform" lived in four places and could drift in any of them. `meta`
 * defaults to the league's own detail line, which is what three of the four
 * wanted; the week overrides it to lead with the window.
 */
export function LeagueHeader<M, C extends View.Children<M> = []>(
  h: Html.H<M>,
  {
    competition,
    league,
    meta,
    children,
  }: { competition: Competition; league: League; meta?: string | undefined; children?: C | undefined },
) {
  return PageHeader(h, {
    title: league.name,
    meta: meta ?? league.detail,
    href: league.url,
    hrefLabel: `Open ${league.name} on the platform`,
    children: [
      h.div
        .class("flex items-center gap-2")
        .children(
          children,
          competition.refreshes &&
            Refresh(h, { key: "refresh", props: { competition: competition.key, league: league.league_id } }),
        ),
    ],
  });
}
