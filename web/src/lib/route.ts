/**
 * The address bar as a value, and the only place the URL shape is written.
 *
 * Parsing and building sit together here and are tested against each other, so
 * there is one answer to what a link looks like. Routing is react-router; this
 * is the vocabulary on top of it. The shell is one layout whose rail and panel
 * read the same values, so it reads the address rather than rendering a
 * subtree per route.
 */
import { matchPath } from "react-router-dom";

/** Every view a competition has, in the order the rail lists them. */
export const VIEWS = ["week", "league", "team", "free-agents"] as const;

/**
 * One vocabulary rather than two: the id in the code is the word in the URL,
 * so there is no table mapping "scout" to "week" for somebody to get wrong.
 */
export type View = (typeof VIEWS)[number];

/** What a competition opens on, and what an unrecognized view falls back to. */
export const DEFAULT_VIEW: View = "week";

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

export const SETTINGS = "/settings";
export const LANDING = "/";

const isView = (value: string | undefined): value is View => VIEWS.includes(value as View);

export function parse(pathname: string): Route {
  // Checked first because a one-segment path is otherwise indistinguishable
  // from a competition, and Settings would resolve to somebody's league.
  if (pathname === SETTINGS) return { page: "settings" };

  const params = matchPath("/:competition/:league?/:view?", pathname)?.params;
  if (!params?.competition) return { page: "landing" };

  return {
    page: "competition",
    competition: params.competition,
    leagueId: params.league ?? null,
    // Narrowed rather than cast: a view nobody wrote — a typo, or a slug from a
    // version that had one more tab — is not a View, and saying so here means
    // no reader downstream has to defend against a value of the wrong shape.
    view: isView(params.view) ? params.view : DEFAULT_VIEW,
  };
}

/** The link to a view. The default view is left off, so the short address and
 *  the long one are the same page rather than two that look different. */
export function href(competition: string, leagueId: string, view: View = DEFAULT_VIEW): string {
  return view === DEFAULT_VIEW ? `/${competition}/${leagueId}` : `/${competition}/${leagueId}/${view}`;
}
