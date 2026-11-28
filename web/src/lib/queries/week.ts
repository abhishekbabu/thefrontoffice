/** A week of a league: the one being played, any other, a day of one, its games, and the judgment of its to-do list. */
import { Query } from "@effect/ui";
import { Schema } from "effect";
import { ApiError, api } from "@/lib/api";
import { wire } from "@/lib/wire";
import { tags, fields, FRESH, fetching, type Answer, type LeagueApi } from "@/lib/queries/cache";

/** The week being played, with its to-do list and its forecast. */
export class GetWeek extends Query.Service<GetWeek>()("api/Week", {
  args: fields.league,
  success: wire<Answer<LeagueApi["week"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id }) => fetching(() => api.league(competition, id).week()));
}

/** Another week of the season, as played or as it projects. */
export class GetWeekOf extends Query.Service<GetWeekOf>()("api/WeekOf", {
  args: { ...fields.league, week: Schema.Number },
  success: wire<Answer<LeagueApi["weekOf"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id, week }) =>
    fetching(() => api.league(competition, id).weekOf(week)),
  );
}

/** One day of a week, both sides as slotted on it; with no `day`, today where the week holds it, else its first. */
export class GetDayOf extends Query.Service<GetDayOf>()("api/DayOf", {
  args: { ...fields.league, week: Schema.Number, day: Schema.NullOr(Schema.String) },
  success: wire<Answer<LeagueApi["dayOf"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id, week, day }) =>
    fetching(() => api.league(competition, id).dayOf(week, day)),
  );
}

/** The real games of any week of the season. */
export class GetGamesOf extends Query.Service<GetGamesOf>()("api/GamesOf", {
  args: { ...fields.league, week: Schema.Number },
  success: wire<Answer<LeagueApi["gamesOf"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id, week }) =>
    fetching(() => api.league(competition, id).gamesOf(week)),
  );
}

/** The kept judgment of the week's to-do list, without asking the model. */
export class GetJudgment extends Query.Service<GetJudgment>()("api/Judgment", {
  args: fields.league,
  success: wire<Answer<LeagueApi["judgment"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id }) =>
    fetching(() => api.league(competition, id).judgment()),
  );
}
