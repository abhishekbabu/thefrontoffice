/**
 * The API client.
 *
 * Its types are not written here: they are the server's response models —
 * the domain models themselves — generated into `schema.ts` from the API's
 * OpenAPI schema. A field added to `ScoutReport` arrives with the next
 * `just api-types`, and `just check-web` fails until it has.
 *
 * Each call is typed by the route it calls, through `Ok`, rather than by a
 * model picked beside it: a route changed to return something else fails to
 * compile here instead of handing a component the wrong shape.
 */
import type { components, operations } from "@/lib/schema";

type Schemas = components["schemas"];

export type Action = Schemas["Action"];
export type ActivityRow = Schemas["ActivityRow"];
export type Capabilities = Schemas["Capabilities"];
export type Competition = Schemas["Competition"];
export type ErrorBody = Schemas["ErrorBody"];
export type ErrorCode = ErrorBody["code"];
export type ItemDecision = Schemas["ItemDecision"];
export type ItemMark = Schemas["ItemMark"];
export type League = Schemas["LeagueRef"];
export type LeagueSchedule = Schemas["LeagueSchedule"];
export type LoginState = Schemas["LoginState"];
export type Move = Schemas["Move"];
export type Outlook = Schemas["Outlook"];
export type Judgment = Schemas["Judgment"];
export type PlayerCall = Schemas["PlayerCall"];
export type PlayerCard = Schemas["PlayerCard"];
export type PlayerDetail = Schemas["PlayerDetail"];
export type PlayerOrder = NonNullable<operations["roster"]["parameters"]["query"]>;
export type PlayerPage = Schemas["PlayerPage"];
export type Remedy = Schemas["Remedy"];
export type ScheduleRow = Schemas["ScheduleRow"];
export type ScoutReport = Schemas["ScoutReport"];
export type Setting = Schemas["Setting"];
export type SettingsGroup = Schemas["SettingsGroup"];
export type Side = Schemas["Side"];
export type Spot = Schemas["Spot"];
export type Stat = Schemas["Stat"];
export type StatTable = Schemas["StatTable"];
export type Subject = Schemas["Subject"];
export type Summary = Schemas["Summary"];
export type Swap = Schemas["Swap"];
export type TaskVerdict = Schemas["TaskVerdict"];
export type TeamRef = Schemas["TeamRef"];
export type TradeIdea = Schemas["TradeIdea"];
export type Turn = Schemas["Turn"];
export type Urgency = Action["urgency"];

/** What a route answers with, named by the route's own function on the server. */
type Ok<Route extends keyof operations> = operations[Route]["responses"][200]["content"]["application/json"];

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    throw failure(await response.json().catch(() => null), `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

const post = <T,>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

const put = <T,>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) });

const segment = encodeURIComponent;

/** `path` asking for the values given, leaving out the ones left empty for the server's own default. */
function withQuery(path: string, query: Record<string, string | number | boolean | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== "" && value !== undefined) params.set(key, String(value));
  }
  const asked = params.toString();
  return asked ? `${path}?${asked}` : path;
}

/**
 * Everything asked of one league, under one base path.
 *
 * Built once per league, so each segment is encoded once and in one place —
 * an id with a slash in it would otherwise address a different route.
 */
export function leagueApi(competition: string, league: string) {
  const base = `/api/${segment(competition)}/leagues/${segment(league)}`;
  return {
    roster: (order: PlayerOrder = {}) => request<Ok<"roster">>(withQuery(`${base}/roster`, order)),
    player: (id: string) => request<Ok<"player">>(`${base}/players/${segment(id)}`),
    summary: () => request<Ok<"summary">>(`${base}/summary`),
    schedule: () => request<Ok<"schedule">>(`${base}/schedule`),
    weeksAhead: () => request<Ok<"weeks_ahead">>(`${base}/weeks-ahead`),
    trades: () => request<Ok<"trades">>(`${base}/trades`),
    teams: () => request<Ok<"teams">>(`${base}/teams`),
    teamRoster: (team: string, order: PlayerOrder = {}) =>
      request<Ok<"team_roster">>(withQuery(`${base}/teams/${segment(team)}/roster`, order)),
    decide: (decision: ItemDecision) => post<Ok<"decide">>(`${base}/items`, decision),
    freeAgents: (query: FreeAgentQuery = {}) => request<Ok<"free_agents">>(withQuery(`${base}/free-agents`, query)),
    freeAgentCalls: (playerIds: string[]) =>
      post<Ok<"free_agent_calls">>(`${base}/free-agents/calls`, { player_ids: playerIds }),
    judgeFreeAgents: (playerIds: string[]) =>
      post<Ok<"judge_free_agents">>(`${base}/free-agents/judge`, { player_ids: playerIds }),
    scout: () => post<Ok<"scout">>(`${base}/scout`, {}),
    judgment: () => request<Ok<"judgment">>(`${base}/judgment`),
    thread: (subject: Subject) => post<Ok<"thread">>(`${base}/threads`, subject),
  };
}

export const api = {
  competitions: () => request<Ok<"list_sports">>("/api/competitions"),
  capabilities: () => request<Ok<"capabilities">>("/api/capabilities"),
  leagues: (competition: string) => request<Ok<"list_leagues">>(`/api/${segment(competition)}/leagues`),
  league: leagueApi,
  /** What has been said in a conversation: the server keeps it, so a reopened chat shows it. */
  turns: (chatId: string) => request<Ok<"turns">>(`/api/chat/${segment(chatId)}`),
  /** Ask the next question; answered with every turn so far, the answer last. */
  ask: (chatId: string, message: string) => post<Ok<"ask">>(`/api/chat/${segment(chatId)}`, { message }),
  settings: () => request<Ok<"read_settings">>("/api/settings"),
  saveSettings: (values: Record<string, string>) => put<Ok<"save_settings">>("/api/settings", { values }),
  /** Start a platform's login, named as a remedy names it: `yahoo`. */
  login: (platform: string) => post<Ok<"start_login">>(`/api/${segment(platform)}/login`, {}),
  loginState: (platform: string) => request<Ok<"login_state">>(`/api/${segment(platform)}/login`),
};
