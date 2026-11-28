/**
 * The shell: the rail of competitions, leagues and views, and the page beside it.
 *
 * The root holds the route. The first arrives through props and every later
 * change as a message, so navigation is in the message log; the rail and the
 * page read the same value, so the shell reads the address rather than
 * rendering a subtree per route.
 */
import { Command, Router, UiSchema, type View as Views } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Option, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { AssistantProvider } from "@/components/league/assistant-provider";
import { CompareProvider } from "@/components/league/compare-provider";
import { IconButton } from "@/components/ui/controls/icon-button";
import { ErrorNote } from "@/components/ui/error-note";
import { Icon } from "@/components/ui/icon";
import { Label } from "@/components/ui/label";
import { TipGroup } from "@/components/ui/overlays/tooltip";
import { Skeleton } from "@/components/ui/skeleton";
import { Loading } from "@/components/ui/state";
import { GetCapabilities, ListCompetitions, ListLeagues } from "@/lib/queries/app";
import { AppRoute, href, pageOf } from "@/lib/route";
import { Mode, PaintMode, systemMode } from "@/lib/theme";
import type { Competition, League } from "@/lib/types";
import { cn } from "@/lib/utils";
import { DEFAULT_VIEW, VIEWS, VIEW_LABELS, type View, offers } from "@/lib/views";
import { RailBlocked, railItem } from "@/rail";
import { Assistant, Landing, NothingConnected, PANELS, SettingsPanel, WIDTH } from "@/pages";

export const AppMessage = UiSchema.TaggedEnum({
  ChangedRoute: { route: AppRoute },
  ClickedMenu: {},
  ClickedScrim: {},
  ClickedMode: {},
  ChangedSystemMode: { mode: Mode },
  ChangedCompetitions: {},
  ChangedLeagues: {},
  PickedLeague: { competition: Schema.String, league: Schema.String },
  RequestedBackFromSettings: {},
});

type AppMessage = typeof AppMessage.Type;

const AppDef = Html.component({
  name: "App",
  props: Schema.Struct({
    route: AppRoute,
    /** The mode the pre-paint script painted, and whether it follows the system's. */
    mode: Mode,
    followsSystem: Schema.Boolean,
    /** Each league's comparison, as the browser held it. */
    compared: Schema.optional(Schema.Record(Schema.String, Schema.Array(Schema.String))),
  }),
  model: Schema.Struct({
    route: AppRoute,
    /**
     * The address the phone menu was opened at, rather than a flag: following
     * a link in it changes the address, which closes it with nothing to undo.
     */
    menuAt: Schema.NullOr(Schema.String),
    mode: Mode,
    followsSystem: Schema.Boolean,
  }),
  message: AppMessage,
  queries: {
    competitions: { query: ListCompetitions, args: () => ({}), onChange: () => AppMessage.ChangedCompetitions() },
    capabilities: { query: GetCapabilities, args: () => ({}) },
    leagues: {
      query: ListLeagues,
      args: ({ model, queries }) => {
        const active = activeOf(model.route, queries.competitions);

        return active ? { competition: active.key } : undefined;
      },
      onChange: () => AppMessage.ChangedLeagues(),
    },
  },
});

/**
 * The competition the address names, if it can be played. Unblocked, not
 * merely configured: credentials being set says nothing about whether a
 * platform will actually answer. No fallback to the first usable one: until
 * one is chosen the landing page is what shows, and choosing for the user is
 * what it avoids.
 */
function activeOf(route: AppRoute, competitions: AsyncResult.AsyncResult<readonly Competition[], unknown>) {
  const page = pageOf(route);

  if (page.page !== "competition" || !AsyncResult.isSuccess(competitions)) return undefined;

  return competitions.value.find((s) => !s.blocked && s.key === page.competition);
}

/**
 * The league the address names. Falling back to the first league is what
 * makes /nfl-sleeper a real address; the correction below then writes the one
 * it resolved into the URL.
 */
function leagueOf(route: AppRoute, leagues: AsyncResult.AsyncResult<readonly League[], unknown>) {
  const page = pageOf(route);

  if (page.page !== "competition" || !AsyncResult.isSuccess(leagues)) return undefined;

  return leagues.value.find((l) => l.league_id === page.leagueId) ?? leagues.value[0];
}

/** The view on screen: one this competition does not offer is its default, which the correction then writes. */
function viewOf(route: AppRoute, active: Competition | undefined): View {
  const page = pageOf(route);

  return page.page === "competition" && (!active || offers(active, page.view)) ? page.view : DEFAULT_VIEW;
}

/**
 * Make the address say what is on screen.
 *
 * One comparison against the canonical link rather than a branch per way of
 * being wrong: it covers the league that /nfl-sleeper resolved to, a view this
 * competition does not offer, and /a/b/matchup spelled the long way. All by
 * replacing, not pushing — being corrected off an address that does not name
 * a page is not a move you should have to press Back through. The query
 * rides along: `?week=5` names what the page shows, not where it is.
 */
const corrected = AppDef.update(($) => {
  const { route } = $.model;
  const page = pageOf(route);

  if (page.page !== "competition") return $.model;

  const active = activeOf(route, $.queries.competitions);

  // A competition nobody can play: a typo, or one whose credentials have
  // gone. Only once the list has arrived — before that they all look alike.
  if (AsyncResult.isSuccess($.queries.competitions) && !active)
    return $.run(Router.replace(AppRoute, AppRoute.Landing()).pipe(Command.asNoop));

  const league = leagueOf(route, $.queries.leagues);

  if (!active || !league) return $.model;

  const settled = href(active.key, league.league_id, viewOf(route, active));

  if (settled === AppRoute.printPath(route) || !("search" in route)) return $.model;

  return Option.match(AppRoute.parse(settled), {
    onNone: () => $.model,
    onSome: (next) =>
      "search" in next
        ? $.run(Router.replace(AppRoute, { ...next, search: route.search }).pipe(Command.asNoop))
        : $.model,
  });
});

const go = (route: AppRoute) => Router.push(AppRoute, route).pipe(Command.asNoop);

const AppNoDeps = AppDef.make({
  init: ($) => ({ route: $.props.route, menuAt: null, mode: $.props.mode, followsSystem: $.props.followsSystem }),
  update: {
    ChangedRoute: ($, { route }) => $.combine(($) => $.evolve({ route }), corrected),
    ChangedCompetitions: corrected,
    ChangedLeagues: corrected,
    ClickedMenu: ($) => {
      const path = AppRoute.printPath($.model.route);

      return $.evolve({ menuAt: $.model.menuAt === path ? null : path });
    },
    ClickedScrim: ($) => $.evolve({ menuAt: null }),
    ClickedMode: ($) => {
      const mode = $.model.mode === "dark" ? "light" : "dark";

      return $.evolve({ mode, followsSystem: false }).run(PaintMode.make({ mode, chosen: true }).pipe(Command.asNoop));
    },
    ChangedSystemMode: ($, { mode }) =>
      $.evolve({ mode }).run(PaintMode.make({ mode, chosen: false }).pipe(Command.asNoop)),
    PickedLeague: ($, { competition, league }) =>
      Option.match(AppRoute.parse(href(competition, league)), {
        onNone: () => $.model,
        onSome: (route) => $.run(go(route)),
      }),
    RequestedBackFromSettings: ($) => $.run(go(AppRoute.Landing())),
  },
  subscriptions: ({ model }) => [
    Router.subscription(AppRoute, model.route, (route) => AppMessage.ChangedRoute({ route })),
    // Follow the OS only while the user has expressed no preference of their own.
    model.followsSystem && systemMode((mode) => AppMessage.ChangedSystemMode({ mode })),
  ],
  view: (h, model) => {
    const { route } = model;
    const page = pageOf(route);
    const path = AppRoute.printPath(route);
    const menuOpen = model.menuAt === path;
    const competitions = AsyncResult.isSuccess(h.queries.competitions) ? h.queries.competitions.value : [];
    const leagues = AsyncResult.isSuccess(h.queries.leagues) ? h.queries.leagues.value : [];
    const active = activeOf(route, h.queries.competitions);
    const league = active ? leagueOf(route, h.queries.leagues) : undefined;
    const view = viewOf(route, active);
    const ai = AsyncResult.isSuccess(h.queries.capabilities) && h.queries.capabilities.value.ai;

    // How many platforms carry each sport, so the rail names the platform only
    // where it distinguishes something.
    const sportCounts = new Map<string, number>();

    for (const s of competitions) sportCounts.set(s.sport, (sportCounts.get(s.sport) ?? 0) + 1);

    /**
     * The column beside the rail: one `if` per state, rather than a ternary
     * chain seven levels deep inside the layout.
     */
    const shell = () => {
      if (page.page === "settings")
        return h.div.attr("data-page", "reading").children(
          SettingsPanel(h, {
            key: "settings",
            props: {},
            onEmit: { RequestedBack: () => AppMessage.RequestedBackFromSettings() },
            fallback: () => Loading(h),
          }),
        );

      if (AsyncResult.isSuccess(h.queries.competitions) && !competitions.some((s) => !s.blocked))
        return NothingConnected(h, competitions);

      if (page.page !== "competition")
        return AsyncResult.isSuccess(h.queries.competitions)
          ? Landing(h, {
              key: "landing",
              props: { competitions: [...competitions] },
              onEmit: {
                Picked: ({ competition, league: picked }) =>
                  AppMessage.PickedLeague({ competition: competition.key, league: picked.league_id }),
              },
              fallback: () => Loading(h),
            })
          : Loading(h);

      if (!active || !league)
        return AsyncResult.isFailure(h.queries.leagues)
          ? ErrorNote(h, { error: AsyncResult.error(h.queries.leagues).pipe(Option.getOrUndefined) })
          : Loading(h);

      // Keyed so a competition or league change remounts the panel. Without it
      // the panel keeps the report it already fetched, and the previous
      // competition's analysis renders under the new league's name — a stale FPL
      // report headed "Huge Euge RR FF", with FPL's figures in the strip.
      const key = `${active.key}:${league.league_id}:${view}`;

      return h.div
        .key(key)
        .attrs({ "data-page": WIDTH[view], class: "animate-rise" })
        .children(
          PANELS[view](h, {
            key,
            props: { competition: active, league, route },
            fallback: () => Loading(h),
          }),
        );
    };

    const page_ = h.div.class(
      // Fixed to the viewport, with each column scrolling on its own. A single
      // page scroll takes the rail with it, so the competition you are on and the
      // way back leave the screen exactly when a long table makes you want them.
      //
      // On a phone the rail is a bar over the page instead, its links behind a
      // menu button: beside the page it left a 390px screen 180px for content.
      "grid h-full grid-rows-[auto_minmax(0,1fr)] overflow-hidden md:grid-cols-[13rem_minmax(0,1fr)] md:grid-rows-1",
    );

    return TipGroup(h, [
      CompareProvider(h, {
        props: { initial: h.props.compared },
        view: () =>
          AssistantProvider(h, {
            view: () =>
              page_.children(
                h.nav
                  .class(
                    "relative z-30 flex flex-col border-b border-border bg-card px-3 py-2 md:gap-6 md:overflow-y-auto md:border-r md:border-b-0 md:py-4",
                  )
                  .children(
                    h.div.class("flex items-center justify-between gap-2").children(
                      h.a
                        .attrs({
                          href: AppRoute.print(AppRoute.Landing()),
                          "aria-label": "Back to all leagues",
                          class:
                            "flex items-center gap-2.5 rounded-md px-1 py-1 text-left transition-colors hover:bg-muted motion-reduce:transition-none",
                        })
                        .children(
                          h.span
                            .class(
                              "flex size-6 shrink-0 items-center justify-center rounded-sm bg-primary text-primary-foreground",
                            )
                            .children(Icon(h, "trophy", { class: "size-3.5", strokeWidth: 2.25 })),
                          h.span.class("font-display text-[15px] font-semibold tracking-tight").children("The Front Office"),
                        ),
                      IconButton(h, {
                        key: "menu",
                        props: {
                          class: "md:hidden",
                          label: menuOpen ? "Close menu" : "Menu",
                          expanded: menuOpen,
                          controls: "rail",
                          icon: menuOpen ? "x" : "menu",
                        },
                        onEmit: { Clicked: () => AppMessage.ClickedMenu() },
                      }),
                    ),
                    // The page under an open menu, shaded as under a drawer, so where the
                    // menu ends reads at a glance; a tap on it closes the menu. Before the
                    // rail, so the rail paints over it.
                    menuOpen &&
                      h.div
                        .attrs({
                          "aria-hidden": "true",
                          class:
                            "absolute inset-x-0 top-full h-dvh bg-scrim transition-opacity duration-150 ease-out starting:opacity-0 motion-reduce:transition-none md:hidden",
                        })
                        .on("click", AppMessage.ClickedScrim()),
                    // Always laid out from md up; below it, only while the menu is open,
                    // dropped over the page rather than pushing it down. It drops in and
                    // lifts out in CSS: `starting:` is where it opens from, and
                    // `transition-discrete` holds it on screen while it fades before
                    // `hidden` takes it away.
                    h.div
                      .attrs({
                        id: "rail",
                        class: cn(
                          "absolute inset-x-0 top-full flex-1 flex-col gap-6 border-b border-border bg-card px-3 pt-2 pb-4 shadow-lg max-md:max-h-[calc(100dvh-3.5rem)] max-md:overflow-y-auto",
                          "max-md:transition-[opacity,translate,display] max-md:transition-discrete max-md:duration-150 max-md:ease-out max-md:motion-reduce:transition-none",
                          "md:static md:flex md:border-b-0 md:p-0 md:shadow-none",
                          menuOpen
                            ? "flex motion-safe:starting:-translate-y-1 starting:opacity-0"
                            : "hidden opacity-0 motion-safe:-translate-y-1 md:translate-y-0 md:opacity-100",
                        ),
                      })
                      .children(
                        // Competition, not sport: these are the NBA, the NFL and the Premier
                        // League. "League" is taken by the group below, which holds the
                        // fantasy leagues you actually play in.
                        Group(h, "Competition", [
                          AsyncResult.isInitial(h.queries.competitions) && Skeleton(h, "mx-2 h-7"),
                          ...competitions.map((s) => {
                            // Two platforms under one sport need telling apart; one does not.
                            const label = (sportCounts.get(s.sport) ?? 0) > 1 ? s.label : s.name;

                            return !s.blocked
                              ? RailLink(h, { to: `/${s.key}`, active: s.key === active?.key }).key(s.key).children(label)
                              : RailBlocked(h, {
                                  key: s.key,
                                  props: { reason: s.blocked.detail },
                                  slots: {
                                    content: [
                                      label,
                                      h.span
                                        .class("font-mono text-[10px] opacity-60")
                                        .children(s.configured ? "blocked" : "off"),
                                    ],
                                  },
                                });
                          }),
                        ]),
                        // Broadest choice to narrowest: the competition, then which of its
                        // leagues, then what to look at in it.
                        active &&
                          leagues.length > 1 &&
                          Group(
                            h,
                            "League",
                            leagues.map((l) =>
                              RailLink(h, {
                                to: href(active.key, l.league_id, view),
                                active: l.league_id === league?.league_id,
                              })
                                .key(l.league_id)
                                .children(h.span.class("truncate").children(l.name)),
                            ),
                          ),
                        // Only once there is a league to address: a tab that cannot be linked
                        // to yet would render as a control that does nothing.
                        active &&
                          league &&
                          Group(
                            h,
                            "View",
                            VIEWS.filter((v) => offers(active, v)).map((v) =>
                              RailLink(h, { to: href(active.key, league.league_id, v), active: v === view })
                                .key(v)
                                .children(VIEW_LABELS[v]),
                            ),
                          ),
                        h.div.class("mt-auto flex items-center gap-1").children(
                          RailLink(h, { to: AppRoute.print(AppRoute.Settings()), active: page.page === "settings", class: "flex-1" }).children(
                            h.span
                              .class("flex items-center gap-2")
                              .children(Icon(h, "settings", { class: "size-3.5" }), "Settings"),
                          ),
                          IconButton(h, {
                            key: "mode",
                            props: {
                              label: model.mode === "dark" ? "Switch to light" : "Switch to dark",
                              side: "top",
                              icon: model.mode === "dark" ? "sun" : "moon",
                            },
                            onEmit: { Clicked: () => AppMessage.ClickedMode() },
                          }),
                        ),
                      ),
                  ),
                // Room at the foot of every page for the assistant's button, which floats
                // over the bottom right: the last row scrolls clear of it.
                h.main.class("min-w-0 overflow-y-auto pb-20").children(
                  // Settings is a place you go and come back from, so it earns the
                  // same rise in as every other view.
                  h.div
                    .key(page.page === "settings" ? "settings" : "app")
                    .class("animate-rise")
                    .children(shell()),
                ),
                // Beside every page rather than on one, and only where there is a model
                // to ask: without one, nothing that needs it is offered.
                ai &&
                  Assistant(h, {
                    key: "assistant",
                    props: { route: page, competition: active ?? null, league: league ?? null },
                  }),
              ),
          }),
      }),
    ]);
  },
});

export const App = AppNoDeps;


function Group<C extends Views.Children<AppMessage>>(h: Html.H<AppMessage>, label: string, children: C) {
  return h.div.class("flex flex-col gap-0.5").children(Label(h, { as: "p", class: "px-2 pb-1.5" }).children(label), children);
}

/**
 * A rail item that goes somewhere, which is most of them.
 *
 * A real link rather than a button that navigates: every view has an address,
 * and an address you cannot open in a new tab, middle-click or preview on
 * hover is only half of one. The Router follows a click on it in the page.
 */
function RailLink(h: Html.H<AppMessage>, { to, active, class: extra }: { to: string; active: boolean; class?: string }) {
  return h.a.attrs({ href: to, class: railItem(active, false, extra), "aria-current": active ? "page" : undefined });
}
