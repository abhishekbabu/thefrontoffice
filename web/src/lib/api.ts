/**
 * The API client.
 *
 * Its types are not written here: they are the server's response models —
 * the domain models themselves — generated into `schema.ts` from the API's
 * OpenAPI schema. A field added to `ScoutReport` arrives with the next
 * `just api-types`, and `just check-web` fails until it has.
 *
 * Each call names its route by the schema's own path, through `openapi-fetch`,
 * so its parameters, body and answer are the route's: a path the server does
 * not serve, or a route changed to return something else, fails to compile
 * here instead of handing a component the wrong shape.
 */
import createClient from "openapi-fetch";
import type { components, operations, paths } from "@/lib/schema";

type Schemas = components["schemas"];

export type Action = Schemas["Action"];
export type ActivityRow = Schemas["ActivityRow"];
export type Capabilities = Schemas["Capabilities"];
export type CaptureStatus = Schemas["CaptureStatus"];
export type Competition = Schemas["Competition"];
export type ErrorBody = Schemas["ErrorBody"];
export type ErrorCode = ErrorBody["code"];
export type ItemDecision = Schemas["ItemDecision"];
export type ItemMark = Schemas["ItemMark"];
export type League = Schemas["LeagueRef"];
export type LeagueSchedule = Schemas["LeagueSchedule"];
export type LoginState = Schemas["LoginState"];
export type Match = Schemas["Match"];
export type Move = Schemas["Move"];
export type MovePlayer = Schemas["MovePlayer"];
export type Outlook = Schemas["Outlook"];
export type Judgment = Schemas["Judgment"];
export type PlayerCall = Schemas["PlayerCall"];
export type PlayerCard = Schemas["PlayerCard"];
export type PlayerDetail = Schemas["PlayerDetail"];
export type PlayerComparison = Schemas["PlayerComparison"];
export type PlayerRef = Schemas["PlayerRef"];
export type PlayerOrder = NonNullable<operations["roster"]["parameters"]["query"]>;
export type PlayerPage = Schemas["PlayerPage"];
export type Remedy = Schemas["Remedy"];
export type ScheduleRow = Schemas["ScheduleRow"];
export type ScoutReport = Schemas["ScoutReport"];
export type Setting = Schemas["Setting"];
export type SettingsGroup = Schemas["SettingsGroup"];
export type Side = Schemas["Side"];
export type Slate = Schemas["Slate"];
export type CategoryLine = Schemas["CategoryLine"];
export type Spot = Schemas["Spot"];
export type Stat = Schemas["Stat"];
export type StatTable = Schemas["StatTable"];
export type Subject = Schemas["Subject"];
export type WeekRange = Schemas["WeekRange"];
export type Summary = Schemas["Summary"];
export type TaskVerdict = Schemas["TaskVerdict"];
export type TeamRef = Schemas["TeamRef"];
export type TradeIdea = Schemas["TradeIdea"];
export type Trades = Schemas["Trades"];
export type Turn = Schemas["Turn"];
export type Urgency = Action["urgency"];
/** What an add is for: this week's games, or the rest of the season. */
export type Pickup = NonNullable<Action["pickup"]>;

/** What to ask for: the competition's own ranking unless a column is named. */
export type FreeAgentQuery = NonNullable<operations["free_agents"]["parameters"]["query"]>;

/**
 * A failure the server described in its own words, ready to show as-is.
 *
 * `code` names the condition and `remedy` what can be done about it, both the
 * server's to say: the page renders the remedy rather than deciding one.
 */
export class ApiError extends Error {
  readonly code: ErrorCode;
  readonly remedy: Remedy | null;

  constructor({ detail, code, remedy }: ErrorBody) {
    super(detail);
    this.code = code;
    this.remedy = remedy;
  }
}

/** Whether `error` is the server saying it no longer holds a conversation: it restarted, or dropped it as the oldest. */
export function isExpired(error: unknown): boolean {
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
export function failure(body: unknown, status: string): ApiError {
  return new ApiError(isErrorBody(body) ? body : { detail: `The server did not answer (${status}).`, code: "error", remedy: null });
}

/**
 * Looked up on each call rather than captured once: a test's interceptor
 * replaces `fetch` after this module has loaded.
 */
const client = createClient<paths>({ fetch: (request) => globalThis.fetch(request) });

/** The answer a call came back with, or the failure it carried, thrown. */
async function settle<T>(pending: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await pending;
  if (!response.ok || data === undefined) throw failure(error ?? null, `${response.status} ${response.statusText}`);
  return data;
}

/** `query` without the values left empty, so the server applies its own default. */
function present<Query extends object>(query: Query): Query {
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
    roster: (order: PlayerOrder = {}) =>
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
    teamRoster: (team: string, order: PlayerOrder = {}) =>
      settle(
        client.GET("/api/competitions/{key}/leagues/{league_id}/teams/{team_id}/roster", {
          params: { path: { ...at, team_id: team }, query: present(order) },
        }),
      ),
    decide: (decision: ItemDecision) =>
      settle(
        client.POST("/api/competitions/{key}/leagues/{league_id}/items", { params: { path: at }, body: decision }),
      ),
    freeAgents: (query: FreeAgentQuery = {}) =>
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
