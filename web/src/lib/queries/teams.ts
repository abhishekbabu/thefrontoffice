/** The teams of a league and what each holds: rosters, untouchables, outlooks and the season. */
import { Query } from "@effect/ui";
import { Schema } from "effect";
import { ApiError, api } from "@/lib/api";
import { wire } from "@/lib/wire";
import { tags, fields, FRESH, fetching, type Answer, type LeagueApi } from "@/lib/queries/cache";

/** Your roster, in the order asked for. */
export class GetRoster extends Query.Service<GetRoster>()("api/Roster", {
  args: { ...fields.league, ...fields.order },
  success: wire<Answer<LeagueApi["roster"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id, ...asked }) =>
    fetching(() => api.league(competition, id).roster(asked)),
  );
}

/** The players on your roster you marked untouchable. */
export class GetUntouchables extends Query.Service<GetUntouchables>()("api/Untouchables", {
  args: fields.league,
  success: wire<Answer<LeagueApi["untouchables"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id }) =>
    fetching(() => api.league(competition, id).untouchables()),
  );
}

export class ListTeams extends Query.Service<ListTeams>()("api/Teams", {
  args: fields.league,
  success: wire<Answer<LeagueApi["teams"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id }) =>
    fetching(() => api.league(competition, id).teams()),
  );
}

/** Another team's roster, in the order asked for. */
export class GetTeamRoster extends Query.Service<GetTeamRoster>()("api/TeamRoster", {
  args: { ...fields.league, team: Schema.String, ...fields.order },
  success: wire<Answer<LeagueApi["teamRoster"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id, team, ...asked }) =>
    fetching(() => api.league(competition, id).teamRoster(team, asked)),
  );
}

/** A team's next few weeks: your own where `team` is empty. */
export class GetOutlook extends Query.Service<GetOutlook>()("api/Outlook", {
  args: { ...fields.league, team: Schema.String },
  success: wire<Answer<LeagueApi["outlook"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id, team }) =>
    fetching(() => api.league(competition, id).outlook(team)),
  );
}

export class GetSeason extends Query.Service<GetSeason>()("api/Season", {
  args: fields.league,
  success: wire<Answer<LeagueApi["season"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id }) =>
    fetching(() => api.league(competition, id).season()),
  );
}
