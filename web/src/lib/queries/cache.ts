/**
 * What every query of the server shares: its tags, how long an answer stays
 * fresh, and how one API call becomes a query's fetch.
 *
 * A query is how two components share one answer and how a command says which
 * answers it changed: every caller of a query with the same arguments sees
 * one entry and one fetch. Each wraps one call of `lib/api.ts` and keeps its
 * answer typed as the server's own model (`wire`), failing with the server's
 * `ApiError`.
 *
 * League state changes on the platform's clock, not ours, and every fetch is a
 * real API call the platform rate-limits, so an answer stays fresh for a
 * minute and nothing retries on its own.
 */
import { Query } from "@effect/ui";
import { Effect, Schema } from "effect";
import { ApiError, api } from "@/lib/api";

export const tags = {
  /** Every query: what a retry after an outage, or a saved setting, invalidates. */
  api: Query.Tag("api"),
  /** Every answer about a league: what a refresh invalidates. */
  league: Query.Tag("league"),
};

/** What a promise-returning call answers, once it settles. */
export type Answer<F> = F extends (...args: never[]) => Promise<infer A> ? A : never;

/** Everything asked of one league. */
export type LeagueApi = ReturnType<typeof api.league>;

/** The arguments every query shares, by what they address. */
export const fields = {
  /** The league a league-scoped query is addressed by. */
  league: { competition: Schema.String, league: Schema.String },
  /** A column to order players by, and which way; left out is the competition's own ranking. */
  order: { sort: Schema.optional(Schema.String), descending: Schema.optional(Schema.Boolean) },
} as const;

/** How long an answer is served without asking again. */
export const FRESH = "1 minute";

/** One API call as a query's fetch: its failure kept typed as the server's `ApiError`. */
export function fetching<A>(call: () => Promise<A>): Effect.Effect<A, ApiError> {
  return Effect.tryPromise({
    try: call,
    catch: (error) =>
      error instanceof ApiError ? error : new ApiError({ message: String(error), code: "error", remedy: null }),
  });
}
