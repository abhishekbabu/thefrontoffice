/** The assistant's conversations. */
import { Query } from "@effect/ui";
import { Schema } from "effect";
import { ApiError, api } from "@/lib/api";
import { wire } from "@/lib/wire";
import { fields, fetching, type Answer, type LeagueApi } from "@/lib/queries/cache";

/** What has been said in a conversation. Always asked again: the server holds it, not this page. */
export class GetTurns extends Query.Service<GetTurns>()("api/Turns", {
  args: { chat: Schema.String },
  success: wire<Answer<typeof api.turns>>(),
  error: ApiError,
  staleTime: 0,
}) {
  static readonly layer = this.toLayer(({ chat }) => fetching(() => api.turns(chat)));
}

/**
 * The assistant's conversation in a league, opened once and kept: `generation`
 * starts a fresh one, after the server dropped the last.
 */
export class OpenChat extends Query.Service<OpenChat>()("api/OpenChat", {
  args: { ...fields.league, generation: Schema.Number },
  success: wire<Answer<LeagueApi["openChat"]>>(),
  error: ApiError,
  staleTime: "Infinity",
  // For the session: collected, the id goes and a blank conversation opens beside the one the server holds.
  idleTimeToLive: "Infinity",
}) {
  static readonly layer = this.toLayer(({ competition, league: id }) =>
    fetching(() => api.league(competition, id).openChat()),
  );
}
