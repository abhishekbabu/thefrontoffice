/**
 * The API client.
 *
 * Its types are not written here: they are the server's response models,
 * generated into `schema.ts` and named in `lib/types.ts`. A field added to
 * `ScoutReport` arrives with the next `just api-types`, and `just check-web`
 * fails until it has.
 *
 * Each call names its route by the schema's own path, through `openapi-fetch`,
 * so its parameters, body and answer are the route's: a path the server does
 * not serve, or a route changed to return something else, fails to compile
 * here instead of handing a component the wrong shape.
 */
import createClient from "openapi-fetch";
import { Schema } from "effect";
import type { components, paths } from "@/lib/schema";
import type { ErrorBody, ErrorCode, FreeAgentQuery, ItemDecision, PlayerOrder, Remedy, Subject } from "@/lib/types";
import { wire } from "@/lib/wire";

/**
 * A failure the server described in its own words, ready to show as-is.
 *
 * `code` names the condition and `remedy` what can be done about it, both the
 * server's to say: the page renders the remedy rather than deciding one. A
 * Schema, so a query that fails carries it as its error and a page reads the
 * remedy off the result.
 */
export class ApiError extends Schema.TaggedError<ApiError>()("ApiError", {
  message: Schema.String,
  code: wire<ErrorCode>(),
  remedy: Schema.NullOr(wire<Remedy>()),
}) {}

/** Whether `error` is the server saying it no longer holds a conversation: it restarted, or dropped it as the oldest. */
export function isExpired(error: Error | null): boolean {
  return error instanceof ApiError && error.code === "chat_expired";
}

function isErrorBody(body: unknown): body is ErrorBody {
  return typeof body === "object" && body !== null && "detail" in body && "code" in body;
}

/**
 * The failure a response carries.
 *
 * The server sends every failure as an `ErrorBody`. A response without one
 * never reached it — a proxy with the server down — and says so by its status.
 */
export function failure(body: ErrorBody | null, status: string): ApiError {
  const { detail, code, remedy } = body ?? { detail: `The server did not answer (${status}).`, code: "error", remedy: null };

  return new ApiError({ message: detail, code, remedy });
}

/**
 * Looked up on each call rather than captured once: a test's interceptor
 * replaces `fetch` after this module has loaded.
 */
const client = createClient<paths>({ fetch: (request) => globalThis.fetch(request) });

/** The answer a call came back with, or the failure it carried, thrown. */
async function settle<T>(pending: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await pending;

  if (!response.ok || data === undefined) throw failure(isErrorBody(error) ? error : null, `${response.status} ${response.statusText}`);

  return data;
}

/** A query's parameters, any of them left out or `undefined`. */
type Loose<Query> = { [K in keyof Query]?: Query[K] | undefined };

/** `query` without the values left empty, so the server applies its own default. */
function present<Query extends object>(query: Loose<Query>): Query {
  // SAFETY: only keys whose value is empty are dropped, and every such key is optional in a query.
  return Object.fromEntries(Object.entries(query).filter(([, value]) => value !== "" && value !== undefined)) as Query;
}

/**
 * Everything asked of one league, addressed by the same two path parameters.
 *
 * `openapi-fetch` encodes each parameter, so an id with a slash in it stays
 * one segment rather than addressing a different route.
 */
export function leagueApi(key: string, league: string) {
  const at = { key, league_id: league };

  return {
    roster: (order: Loose<PlayerOrder> = {}) =>
      settle(client.GET("/api/competitions/{key}/leagues/{league_id}/roster", { params: { path: at, query: present(order) } })),
    player: (id: string) =>
      settle(
        client.GET("/api/competitions/{key}/leagues/{league_id}/players/{player_id}", {
          params: { path: { ...at, player_id: id } },
        }),
      ),
    /** One tab of his drawer read only when opened (`PlayerDetail.deferred`). */
    playerTab: (id: string, tab: string) =>
      settle(
        client.GET("/api/competitions/{key}/leagues/{league_id}/players/{player_id}/tabs/{tab}", {
          params: { path: { ...at, player_id: id, tab } },
        }),
      ),
    compare: (ids: string[]) =>
      settle(client.GET("/api/competitions/{key}/leagues/{league_id}/compare", { params: { path: at, query: { ids } } })),
    searchPlayers: (search: string) =>
      settle(
        client.GET("/api/competitions/{key}/leagues/{league_id}/players", {
          params: { path: at, query: present({ search }) },
        }),
      ),
    /** The week being played, with its to-do list and its forecast. */
    week: () => settle(client.GET("/api/competitions/{key}/leagues/{league_id}/week", { params: { path: at } })),
    /** Another week of the season, as played or as it projects; the week being played is `week`. */
    weekOf: (week: number) =>
      settle(
        client.GET("/api/competitions/{key}/leagues/{league_id}/weeks/{week}", { params: { path: { ...at, week } } }),
      ),
    /** One day of a week, both sides as slotted on it; with no `day`, today where the week holds it, else its first. */
    dayOf: (week: number, day: string | null) =>
      settle(
        client.GET("/api/competitions/{key}/leagues/{league_id}/weeks/{week}/day", {
          params: { path: { ...at, week }, query: day ? { day } : {} },
        }),
      ),
    /** The real games of any week of the season, the week being played included. */
    gamesOf: (week: number) =>
      settle(
        client.GET("/api/competitions/{key}/leagues/{league_id}/weeks/{week}/games", {
          params: { path: { ...at, week } },
        }),
      ),
    season: () => settle(client.GET("/api/competitions/{key}/leagues/{league_id}/season", { params: { path: at } })),
    /** A team's next few weeks: your own unless another team is named. */
    outlook: (team = "") =>
      settle(
        team
          ? client.GET("/api/competitions/{key}/leagues/{league_id}/teams/{team_id}/outlook", {
              params: { path: { ...at, team_id: team } },
            })
          : client.GET("/api/competitions/{key}/leagues/{league_id}/outlook", { params: { path: at } }),
      ),
    trades: () => settle(client.GET("/api/competitions/{key}/leagues/{league_id}/trades", { params: { path: at } })),
    teams: () => settle(client.GET("/api/competitions/{key}/leagues/{league_id}/teams", { params: { path: at } })),
    teamRoster: (team: string, order: Loose<PlayerOrder> = {}) =>
      settle(
        client.GET("/api/competitions/{key}/leagues/{league_id}/teams/{team_id}/roster", {
          params: { path: { ...at, team_id: team }, query: present(order) },
        }),
      ),
    /** The players on your roster you marked untouchable. */
    untouchables: () =>
      settle(client.GET("/api/competitions/{key}/leagues/{league_id}/untouchables", { params: { path: at } })),
    /** Mark one player untouchable or clear his mark; answered with every untouchable after it. */
    markUntouchable: (mark: components["schemas"]["UntouchableMark"]) =>
      settle(
        client.POST("/api/competitions/{key}/leagues/{league_id}/untouchables", { params: { path: at }, body: mark }),
      ),
    decide: (decision: ItemDecision) =>
      settle(
        client.POST("/api/competitions/{key}/leagues/{league_id}/items", { params: { path: at }, body: decision }),
      ),
    freeAgents: (query: Loose<FreeAgentQuery> = {}) =>
      settle(
        client.GET("/api/competitions/{key}/leagues/{league_id}/free-agents", {
          params: { path: at, query: present(query) },
        }),
      ),
    /** The calls already made on these free agents, without asking the model. */
    freeAgentCalls: (playerIds: string[]) =>
      settle(
        client.GET("/api/competitions/{key}/leagues/{league_id}/free-agents/calls", {
          params: { path: at, query: { ids: playerIds } },
        }),
      ),
    /** Ask the model for a call on each of these free agents. */
    judgeFreeAgents: (playerIds: string[]) =>
      settle(
        client.POST("/api/competitions/{key}/leagues/{league_id}/free-agents/calls", {
          params: { path: at },
          body: { player_ids: playerIds },
        }),
      ),
    /** Judge the week's to-do list, or return the kept judgment where nothing has changed. */
    judge: () => settle(client.POST("/api/competitions/{key}/leagues/{league_id}/judgment", { params: { path: at } })),
    /** The kept judgment, without asking the model. */
    judgment: () =>
      settle(client.GET("/api/competitions/{key}/leagues/{league_id}/judgment", { params: { path: at } })),
    /** Drop what the server keeps of this league that a move or a new week changes. */
    refresh: () =>
      settle(client.POST("/api/competitions/{key}/leagues/{league_id}/refresh", { params: { path: at } })),
    /** Open the assistant's conversation in this league; asked through `api.ask`. */
    openChat: () => settle(client.POST("/api/competitions/{key}/leagues/{league_id}/chats", { params: { path: at } })),
  };
}

export const api = {
  competitions: () => settle(client.GET("/api/competitions")),
  capabilities: () => settle(client.GET("/api/capabilities")),
  leagues: (key: string) => settle(client.GET("/api/competitions/{key}/leagues", { params: { path: { key } } })),
  league: leagueApi,
  /** What has been said in a conversation: the server keeps it, so a reopened chat shows it. */
  turns: (chatId: string) => settle(client.GET("/api/chats/{chat_id}", { params: { path: { chat_id: chatId } } })),
  /** Ask the next question with what is on screen; answered with every turn so far, the answer last. */
  ask: (chatId: string, message: string, onScreen: Subject[] = []) =>
    settle(
      client.POST("/api/chats/{chat_id}/turns", {
        params: { path: { chat_id: chatId } },
        body: { message, on_screen: onScreen },
      }),
    ),
  settings: () => settle(client.GET("/api/settings")),
  saveSettings: (values: Record<string, string>) => settle(client.PUT("/api/settings", { body: { values } })),
  /** Start a platform's login, named as a remedy names it: `yahoo`. */
  login: (platform: string) =>
    settle(client.POST("/api/platforms/{platform}/login", { params: { path: { platform } } })),
  loginState: (platform: string) =>
    settle(client.GET("/api/platforms/{platform}/login", { params: { path: { platform } } })),
  /** When a platform's browser sync last stored anything, and which leagues it holds. */
  captureStatus: (platform: string) =>
    settle(client.GET("/api/platforms/{platform}/capture", { params: { path: { platform } } })),
};
