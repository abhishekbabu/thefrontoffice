/**
 * The API client.
 *
 * Its types are not written here: they are the server's response models —
 * the domain models themselves — generated into `schema.ts` from the API's
 * OpenAPI schema. A field added to `ScoutReport` arrives with the next
 * `just api-types`, and `just check-web` fails until it has.
 */
import type { components, operations } from "@/lib/schema";

type Schemas = components["schemas"];

export type Action = Schemas["Action"];
export type ActivityRow = Schemas["ActivityRow"];
export type Capabilities = Schemas["Capabilities"];
export type Competition = Schemas["Competition"];
export type ErrorCode = Schemas["ErrorBody"]["code"];
export type ItemDecision = Schemas["ItemDecision"];
export type League = Schemas["LeagueRef"];
export type LeagueSchedule = Schemas["LeagueSchedule"];
export type LoginState = Schemas["LoginState"];
export type Move = Schemas["Move"];
export type PlayerCall = Schemas["PlayerCall"];
export type PlayerCard = Schemas["PlayerCard"];
export type PlayerDetail = Schemas["PlayerDetail"];
export type PlayerPage = Schemas["PlayerPage"];
export type Remedy = Schemas["Remedy"];
export type RememberedReport = Schemas["Remembered_ScoutReport_"];
export type ScheduleRow = Schemas["ScheduleRow"];
export type ScoutReport = Schemas["ScoutReport"];
export type Setting = Schemas["Setting"];
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
export type Urgency = Action["urgency"];
export type WeekAhead = Schemas["WeekAhead"];

/** What to ask for: the competition's own ranking unless a column is named. */
export type FreeAgentQuery = NonNullable<
  operations["free_agents_api__competition__leagues__league_id__free_agents_get"]["parameters"]["query"]
>;

/**
 * A failure the server described in its own words, ready to show as-is.
 *
 * `code` names the condition and `remedy` what can be done about it, both the
 * server's to say: the page renders the remedy rather than deciding one.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: ErrorCode = "error",
    readonly remedy: Remedy | null = null,
  ) {
    super(message);
  }
}

/** FastAPI's own validation failure: one entry per field it refused. */
type Refusal = { msg: string };

/**
 * The sentence a failed response carries.
 *
 * Every expected failure carries `detail` written for a person. A request the
 * server refused as malformed carries a list instead, one entry per field;
 * anything with neither is a genuine fault and gets the status line.
 */
export function failureMessage(detail: unknown, status: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((refusal: Refusal) => refusal.msg).join("; ");
  return status;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const status = `${response.status} ${response.statusText}`;
    throw new ApiError(failureMessage(body?.detail, status), body?.code ?? "error", body?.remedy ?? null);
  }
  return response.json() as Promise<T>;
}

const post = <T,>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

const put = <T,>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) });

const segment = encodeURIComponent;

/**
 * Everything asked of one league, under one base path.
 *
 * Built once per league, so each segment is encoded once and in one place —
 * an id with a slash in it would otherwise address a different route.
 */
export function leagueApi(competition: string, league: string) {
  const base = `/api/${segment(competition)}/leagues/${segment(league)}`;
  return {
    roster: () => request<PlayerCard[]>(`${base}/roster`),
    player: (id: string) => request<PlayerDetail>(`${base}/players/${segment(id)}`),
    summary: () => request<Summary>(`${base}/summary`),
    schedule: () => request<LeagueSchedule>(`${base}/schedule`),
    weeksAhead: () => request<WeekAhead[]>(`${base}/weeks-ahead`),
    trades: () => request<TradeIdea[]>(`${base}/trades`),
    teams: () => request<TeamRef[]>(`${base}/teams`),
    teamRoster: (team: string) => request<PlayerCard[]>(`${base}/teams/${segment(team)}/roster`),
    decide: (decision: ItemDecision) => post<unknown>(`${base}/items`, decision),
    freeAgents: (query: FreeAgentQuery = {}) => {
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(query)) {
        if (value !== "" && value !== undefined) params.set(key, String(value));
      }
      return request<PlayerPage>(`${base}/free-agents?${params}`);
    },
    freeAgentCalls: (playerIds: string[]) =>
      post<PlayerCall[]>(`${base}/free-agents/calls`, { player_ids: playerIds }),
    judgeFreeAgents: (playerIds: string[]) =>
      post<PlayerCall[]>(`${base}/free-agents/judge`, { player_ids: playerIds }),
    scout: () => post<ScoutReport>(`${base}/scout`, {}),
    judgment: () => request<RememberedReport | null>(`${base}/judgment`),
    thread: (subject: Subject) => post<Schemas["Thread"]>(`${base}/threads`, subject),
  };
}

export const api = {
  competitions: () => request<Competition[]>("/api/competitions"),
  capabilities: () => request<Capabilities>("/api/capabilities"),
  leagues: (competition: string) => request<League[]>(`/api/${segment(competition)}/leagues`),
  league: leagueApi,
  ask: (chatId: string, message: string) => post<Schemas["Reply"]>(`/api/chat/${segment(chatId)}`, { message }),
  settings: () => request<Setting[]>("/api/settings"),
  saveSettings: (values: Record<string, string>) => put<Setting[]>("/api/settings", { values }),
  yahooLogin: () => post<LoginState>("/api/yahoo/login", {}),
  yahooLoginState: () => request<LoginState>("/api/yahoo/login"),
};
