/**
 * The API's types, named once for the client: each the server's own response
 * model (the domain model itself) as generated into `schema.ts` from its
 * OpenAPI schema, so a field added in Python arrives with `just api-types`.
 */
import type { components, operations } from "@/lib/schema";

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
