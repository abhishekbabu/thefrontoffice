/** Players across a league: the trades, side-by-side comparisons, searches and one player's drawer. */
import { Query } from "@effect/ui";
import { Schema } from "effect";
import { ApiError, api } from "@/lib/api";
import { wire } from "@/lib/wire";
import { tags, fields, FRESH, fetching, type Answer, type LeagueApi } from "@/lib/queries/cache";

export class GetTrades extends Query.Service<GetTrades>()("api/Trades", {
  args: fields.league,
  success: wire<Answer<LeagueApi["trades"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id }) =>
    fetching(() => api.league(competition, id).trades()),
  );
}

/** Players side by side, by id. */
export class GetComparison extends Query.Service<GetComparison>()("api/Compare", {
  args: { ...fields.league, ids: Schema.Array(Schema.String) },
  success: wire<Answer<LeagueApi["compare"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id, ids }) =>
    fetching(() => api.league(competition, id).compare([...ids])),
  );
}

/** Players of the league whose names hold `search`. */
export class SearchPlayers extends Query.Service<SearchPlayers>()("api/SearchPlayers", {
  args: { ...fields.league, search: Schema.String },
  success: wire<Answer<LeagueApi["searchPlayers"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id, search }) =>
    fetching(() => api.league(competition, id).searchPlayers(search)),
  );
}

/** One player's drawer. */
export class GetPlayer extends Query.Service<GetPlayer>()("api/Player", {
  args: { ...fields.league, player: Schema.String },
  success: wire<Answer<LeagueApi["player"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id, player }) =>
    fetching(() => api.league(competition, id).player(player)),
  );
}

/** One tab of a player's drawer, read only when opened (`PlayerDetail.deferred`). */
export class GetPlayerTab extends Query.Service<GetPlayerTab>()("api/PlayerTab", {
  args: { ...fields.league, player: Schema.String, tab: Schema.String },
  success: wire<Answer<LeagueApi["playerTab"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id, player, tab }) =>
    fetching(() => api.league(competition, id).playerTab(player, tab)),
  );
}
