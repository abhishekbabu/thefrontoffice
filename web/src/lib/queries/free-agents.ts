/** The free agents, and the calls made on them. */
import { Query } from "@effect/ui";
import { Schema } from "effect";
import { ApiError, api } from "@/lib/api";
import { wire } from "@/lib/wire";
import { tags, fields, FRESH, fetching, type Answer, type LeagueApi } from "@/lib/queries/cache";

/** A page of the free agents, filtered and ordered as asked. */
export class GetFreeAgents extends Query.Service<GetFreeAgents>()("api/FreeAgents", {
  args: {
    ...fields.league,
    ...fields.order,
    offset: Schema.Number,
    search: Schema.String,
    position: Schema.String,
    view: Schema.String,
  },
  success: wire<Answer<LeagueApi["freeAgents"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id, sort, descending, ...asked }) =>
    fetching(() => api.league(competition, id).freeAgents({ ...asked, sort, descending })),
  );
}

/** The calls already made on these free agents, without asking the model. */
export class GetFreeAgentCalls extends Query.Service<GetFreeAgentCalls>()("api/FreeAgentCalls", {
  args: { ...fields.league, ids: Schema.Array(Schema.String) },
  success: wire<Answer<LeagueApi["freeAgentCalls"]>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition, league: id, ids }) =>
    fetching(() => api.league(competition, id).freeAgentCalls([...ids])),
  );
}
