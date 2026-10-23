/**
 * The API client.
 *
 * Types here mirror the response models in `adapters/inbound/web/api.py`, which
 * are the domain models themselves — so a field added to `ScoutReport` shows up
 * as a typecheck failure here rather than as an undefined at runtime.
 */

export type Competition = {
  /** Identifies this entry in every route and picker: "nba-yahoo". */
  key: string;
  /** basketball | football | soccer — groups the competitions that share one. */
  sport: string;
  /** Which competition this is: "nba", "nfl", "premier-league". */
  competition: string;
  platform: string;
  label: string;
  /** Whether its free agents can be judged — offered only where they can. */
  judges_wire: boolean;
  /** Whether the credentials this competition needs are set. */
  configured: boolean;
  requires: string;
  /** Whether it can actually be used. Configured is necessary, not sufficient. */
  ready: boolean;
  /** What stands in the way, and which remedy to offer. Empty when ready. */
  blocked_reason: string;
  blocked_code: string;
};

export type League = { league_id: string; name: string; detail: string; url: string };

export type MoveAction = "ADD" | "DROP" | "START" | "BENCH" | "TRANSFER" | "CAPTAIN" | "MONITOR";

export type Move = {
  action: MoveAction;
  player: string;
  position: string;
  team: string;
  metric: string;
  rationale: string;
  replaces: string;
  replaces_rationale: string;
};

export type Tone = "neutral" | "good" | "warning";

export type Stat = { label: string; value: string; tone: Tone };

/** One place in a lineup, or one player on a bench. */
export type Spot = {
  player_id: string;
  slot: string;
  player: string;
  detail: string;
  value: string;
  tone: Tone;
};

/** A change the numbers already imply, before anyone has judged them. */
export type Swap = { start: string; out: string; gain: string };

/** now: costs points this week if left. soon: before this week's next
    deadline. later: planning for a week still to come. */
export type Urgency = "now" | "soon" | "later";

/** One decision the week asks of the manager, and why it is one. */
export type Action = {
  kind: "lineup" | "waiver" | "trade";
  urgency: Urgency;
  /** Which decision this is, stable while it stays the same one. */
  key: string;
  /** What the item currently says; a verdict on a different one is stale. */
  fingerprint: string;
  title: string;
  reason: string;
  /** The deadline as a label; empty where the platform publishes none. */
  when: string;
  /** The player the move turns on, to open their detail. */
  player_id: string;
  /** Who the move takes out of the lineup, by id; empty where nobody. */
  replaces: string;
  /** For a pickup, who to release to make room. Empty where a spot is open. */
  drop: string;
  /** What the move does to the chance of winning — 0.028 for +2.8 points; null where unpriced. */
  win_change: number | null;
  /** What the move rests on beyond the projection, one line per player:
      the matchup and the role. Toned by the matchup, which the text also says. */
  evidence: Stat[];
  /** The model's judgement, once a report has been run; null before. */
  verdict: TaskVerdict | null;
  /** What the manager decided: hidden until it changes, or until a time. */
  hidden: "dismissed" | "snoozed" | null;
  snoozed_until: string | null;
  /** Dismissed earlier, and changed since — so shown again, saying why. */
  resurfaced: boolean;
};

/** One decision about one to-do item. */
export type ItemDecision =
  | { key: string; decision: "dismiss"; fingerprint: string }
  | { key: string; decision: "snooze"; until: string }
  | { key: string; decision: "restore" };

/** The model's word on one computed to-do item, by its id. */
export type TaskVerdict = {
  task: string;
  decision: "AGREE" | "OVERRULE" | "WAIT";
  reason: string;
};

/** The week played many times over: the chance of winning, and the likely margin. */
export type Forecast = {
  win: number;
  margin: { low: number; median: number; high: number };
  simulations: number;
  moves: Record<string, number>;
  best_move: string;
};

/** One team in a matchup — yours, or the one you are playing. */
export type Side = { name: string; detail: string; points: string; lineup: Spot[]; bench: Spot[] };

export type Summary = {
  headline: Stat[];
  mine: Side | null;
  /** Null when the week has no fixture, which is not a nil-nil scoreline. */
  opponent: Side | null;
  swaps: Swap[];
  /** Most urgent first. Null where the competition computes none yet, which
      is not the same answer as an empty list: nothing to do. */
  actions: Action[] | null;
  fixtures: Stat[];
  /** One-time advantages the manager can spend; null in a competition with none. */
  boosts: StatGroup | null;
  /** The matchup simulated; null where it cannot be, or there is no opponent. */
  forecast: Forecast | null;
  /** When this week actually is, already formatted. A week with no dates on it
      is a number, and the number is the one thing already known. */
  window: string;
};

export type ScoutReport = {
  situation: string;
  focus: string[];
  moves: Move[];
  strategy: string;
  /** Read off the platform by the provider, not written by the model. */
  headline: Stat[];
  verdicts: TaskVerdict[];
  /** The to-do items as computed, each carrying its verdict. Filled by the
      application, never by the model; empty where none are computed. */
  tasks: Action[];
};

/** The model's call on one available player, shown on his row. */
export type PlayerCall = {
  player_id: string;
  decision: "ADD" | "WATCH" | "PASS";
  /** For ADD, who on the roster makes way. */
  drop: string;
  reason: string;
  judged_at: string | null;
  /** The player's situation has moved since the call was made. */
  stale: boolean;
};

/** What a conversation is about: one to-do item by its key, or one player by id. */
export type Subject = { kind: "task" | "player"; key: string };

/** Any model answer, kept with a digest of what it was given and when. */
export type Remembered<T> = { answer: T; answered_at: string; inputs: string };

/** What this installation can do, as opposed to what it knows how to do. */
export type Capabilities = { ai: boolean };

export type Setting = {
  key: string;
  field: string;
  secret: boolean;
  /** Whether a value is set. For a secret this is all the client is ever told. */
  present: boolean;
  /** Always empty for a secret; a secret's characters never leave the server. */
  value: string;
  /** A shell variable is overriding .env, so an edit here will not take effect. */
  shadowed: boolean;
  /** Which control to render: text, boolean, integer, number or choice. */
  kind: "text" | "boolean" | "integer" | "number" | "choice";
  choices: string[];
  /** What is in force, including a default. Shown so an empty field is not
   *  mistaken for an unset one. */
  effective: string;
};
/** A player as a table row: the competition's own columns, plus what a column cannot be. */
export type PlayerCard = {
  player_id: string;
  columns: Record<string, string>;
  /** The number behind a formatted column, for the columns that have one. */
  values: Record<string, number>;
  tone: Tone;
};

/** What to ask for: the competition's own ranking unless a column is named. */
export type FreeAgentQuery = {
  offset?: number;
  limit?: number;
  sort?: string;
  descending?: boolean;
  position?: string;
  search?: string;
};

/** One window onto a player list, and how much there is to page through. */
export type PlayerPage = {
  players: PlayerCard[];
  total: number;
  offset: number;
  positions: string[];
};

/** A handful of related figures under a heading. */
export type StatGroup = { title: string; stats: Stat[] };

export type ScheduleRow = {
  label: string;
  date: string;
  opponent: string;
  detail: string;
  result: string;
  tone: Tone;
  is_current: boolean;
};

export type StandingRow = {
  rank: number;
  name: string;
  detail: string;
  record: string;
  points: string;
  /** Addresses this team's roster. Empty where the platform cannot serve one. */
  team_id: string;
  /** Chance of a playoff place, formatted. Empty where the season is not simulated. */
  playoffs: string;
  is_mine: boolean;
};

export type Match = {
  label: string;
  home: string;
  away: string;
  detail: string;
  tone: Tone;
};

export type ActivityRow = {
  when: string;
  who: string;
  what: string;
  detail: string;
  tone: Tone;
};

export type TeamRef = {
  team_id: string;
  name: string;
  detail: string;
  /** This team on its own platform, where there is such a page. */
  url: string;
  is_mine: boolean;
};

export type LeagueSchedule = {
  season: ScheduleRow[];
  standings: StandingRow[];
  matches: Match[];
  activity: ActivityRow[];
};

/**
 * What a cell reads where a period has no answer at all.
 *
 * Kept in step with `NOT_APPLICABLE` in `domain/models.py`. Part of the
 * contract rather than a formatting choice: a nought is an answer and this is
 * the absence of one, which is why they are shown differently.
 */
export const NOT_APPLICABLE = "N/A";

export type StatRow = {
  label: string;
  /** One per column, in the same order; NOT_APPLICABLE where there is no answer. */
  values: string[];
  tone: Tone;
};

export type StatTable = {
  title: string;
  columns: string[];
  rows: StatRow[];
};

export type PlayerDetail = {
  player_id: string;
  name: string;
  position: string;
  /** The club as a table spells it: "DET". */
  team: string;
  /** The same club in full — "Detroit Lions". Empty falls back to `team`. */
  team_name: string;
  /** The club's crest, or empty where the competition has none. */
  team_logo_url: string;
  /** The bare figure, empty when there is none — which is not zero. */
  headline: string;
  /** What that figure is, or why there is not one. */
  headline_label: string;
  /** This player on the platform's own site, where one exists. */
  url: string;
  note: string;
  image_url: string;
  tone: Tone;
  groups: StatGroup[];
  tables: StatTable[];
};

/**
 * A failure the server described in its own words, ready to show as-is.
 *
 * `code` names conditions this app can offer to fix. Matching on it rather than
 * on the message leaves the wording free to change.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string = "error",
  ) {
    super(message);
  }
}

export type LoginState = { status: "idle" | "running" | "ok" | "failed"; detail: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    // Every expected failure carries `detail` written for a person; anything
    // without one is a genuine fault and gets the status line instead.
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail ?? `${response.status} ${response.statusText}`, body?.code);
  }
  return response.json() as Promise<T>;
}

const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

const put = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const api = {
  competitions: () => request<Competition[]>("/api/competitions"),
  leagues: (competition: string) => request<League[]>(`/api/${competition}/leagues`),
  roster: (competition: string, league: string) => request<PlayerCard[]>(`/api/${competition}/leagues/${league}/roster`),
  player: (competition: string, league: string, id: string) =>
    request<PlayerDetail>(`/api/${competition}/leagues/${league}/players/${id}`),
  summary: (competition: string, league: string) => request<Summary>(`/api/${competition}/leagues/${league}/summary`),
  schedule: (competition: string, league: string) =>
    request<LeagueSchedule>(`/api/${competition}/leagues/${league}/schedule`),
  decide: (competition: string, league: string, decision: ItemDecision) =>
    post<unknown>(`/api/${competition}/leagues/${league}/items`, decision),
  freeAgentCalls: (competition: string, league: string, playerIds: string[]) =>
    post<PlayerCall[]>(`/api/${competition}/leagues/${league}/free-agents/calls`, { player_ids: playerIds }),
  judgeFreeAgents: (competition: string, league: string, playerIds: string[]) =>
    post<PlayerCall[]>(`/api/${competition}/leagues/${league}/free-agents/judge`, { player_ids: playerIds }),
  freeAgents: (competition: string, league: string, query: FreeAgentQuery = {}) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== "" && value !== undefined) params.set(key, String(value));
    }
    return request<PlayerPage>(`/api/${competition}/leagues/${league}/free-agents?${params}`);
  },
  teams: (competition: string, league: string) => request<TeamRef[]>(`/api/${competition}/leagues/${league}/teams`),
  teamRoster: (competition: string, league: string, team: string) =>
    request<PlayerCard[]>(`/api/${competition}/leagues/${league}/teams/${encodeURIComponent(team)}/roster`),
  scout: (competition: string, league: string) => post<ScoutReport>(`/api/${competition}/leagues/${league}/scout`, {}),
  thread: (competition: string, league: string, subject: Subject) =>
    post<{ chat_id: string }>(`/api/${competition}/leagues/${league}/threads`, subject),
  judgment: (competition: string, league: string) =>
    request<Remembered<ScoutReport> | null>(`/api/${competition}/leagues/${league}/judgment`),
  ask: (chatId: string, message: string) => post<{ answer: string }>(`/api/chat/${chatId}`, { message }),
  capabilities: () => request<Capabilities>("/api/capabilities"),
  settings: () => request<Setting[]>("/api/settings"),
  yahooLogin: () => post<LoginState>("/api/yahoo/login", {}),
  yahooLoginState: () => request<LoginState>("/api/yahoo/login"),
  saveSettings: (values: Record<string, string>) => put<Setting[]>("/api/settings", { values }),
};
