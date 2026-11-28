/**
 * The address bar as a value, and the only place the URL shape is written.
 *
 * `AppRoute` is the table the Router matches and prints with; `parse` and
 * `href` are the vocabulary on top of it, tested against each other, so there
 * is one answer to what a link looks like. The shell is one layout whose rail
 * and panel read the same values, so it reads the address rather than
 * rendering a subtree per route.
 */
import { Route as Routes } from "@effect/ui";
import { Option, Schema } from "effect";
import { DEFAULT_VIEW, VIEWS, type View } from "@/lib/views";

/**
 * What a page shows that is not where it is: `?week=5`, `?day=2026-11-03`,
 * `?team=4`. A value that does not read — `?week=abc` — is dropped from the
 * address rather than taken for a page of its own.
 */
const search = {
  week: Schema.optional(Schema.NumberFromString),
  day: Schema.optional(Schema.String),
  team: Schema.optional(Schema.String),
};

/** Every address the app answers, as the Router reads and prints it. */
export const AppRoute = Routes.union({
  Landing: Routes.make("/"),
  Settings: Routes.make("/settings"),
  Competition: Routes.make("/:competition", { params: { competition: Schema.String }, search }),
  League: Routes.make("/:competition/:league", {
    params: { competition: Schema.String, league: Schema.String },
    search,
  }),
  View: Routes.make("/:competition/:league/:view", {
    params: { competition: Schema.String, league: Schema.String, view: Schema.String },
    search,
  }),
  Elsewhere: Routes.make("/*"),
});

export type AppRoute = typeof AppRoute.Type;

/**
 * Where the address points.
 *
 * A union rather than three loose values, because they are not independent:
 * there is no league on the landing page and no view in Settings, and every
 * reader that took them separately had to re-derive which combination it was
 * looking at.
 */
export type Route =
  | { page: "landing" }
  | { page: "settings" }
  /** A league is optional here: /nfl-sleeper is somewhere you can arrive by
   *  trimming a URL, and resolves to your first league once they load. */
  | { page: "competition"; competition: string; leagueId: string | null; view: View };

const isView = (value: string | undefined): value is View => VIEWS.some((view) => view === value);

/** The page a matched address is. */
export function pageOf(route: AppRoute): Route {
  return AppRoute.match(route, {
    Landing: (): Route => ({ page: "landing" }),
    Settings: (): Route => ({ page: "settings" }),
    Competition: ({ params }): Route => ({
      page: "competition",
      competition: params.competition,
      leagueId: null,
      view: DEFAULT_VIEW,
    }),
    League: ({ params }): Route => ({
      page: "competition",
      competition: params.competition,
      leagueId: params.league,
      view: DEFAULT_VIEW,
    }),
    View: ({ params }): Route => ({
      page: "competition",
      competition: params.competition,
      leagueId: params.league,
      // Narrowed rather than cast: a view nobody wrote — a typo, or a slug from a
      // version that had one more tab — is not a View, and saying so here means
      // no reader downstream has to defend against a value of the wrong shape.
      view: isView(params.view) ? params.view : DEFAULT_VIEW,
    }),
    // Too deep to be a page: the landing page, as an address nobody wrote.
    Elsewhere: (): Route => ({ page: "landing" }),
  });
}

/** The page `pathname` is. */
export function parse(pathname: string): Route {
  return Option.match(AppRoute.parse(pathname), {
    onNone: (): Route => ({ page: "landing" }),
    onSome: pageOf,
  });
}

/** The link to a view. The default view is left off, so the short address and
 *  the long one are the same page rather than two that look different. */
export function href(competition: string, leagueId: string, view: View = DEFAULT_VIEW): string {
  return view === DEFAULT_VIEW
    ? AppRoute.print(AppRoute.League({ params: { competition, league: leagueId } }))
    : AppRoute.print(AppRoute.View({ params: { competition, league: leagueId, view } }));
}
