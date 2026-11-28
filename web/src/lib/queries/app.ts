/** The app around the leagues: what it can do, the competitions and their leagues, settings and logins. */
import { Query } from "@effect/ui";
import { Schema } from "effect";
import { ApiError, api } from "@/lib/api";
import { wire } from "@/lib/wire";
import { tags, FRESH, fetching, type Answer } from "@/lib/queries/cache";

/** What this installation can do: whether a model is configured, and the engines' limits. */
export class GetCapabilities extends Query.Service<GetCapabilities>()("api/Capabilities", {
  success: wire<Answer<typeof api.capabilities>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api],
}) {
  static readonly layer = this.toLayer(() => fetching(api.capabilities));
}

export class ListCompetitions extends Query.Service<ListCompetitions>()("api/Competitions", {
  success: wire<Answer<typeof api.competitions>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api],
}) {
  static readonly layer = this.toLayer(() => fetching(api.competitions));
}

export class ListLeagues extends Query.Service<ListLeagues>()("api/Leagues", {
  args: { competition: Schema.String },
  success: wire<Answer<typeof api.leagues>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api, tags.league],
}) {
  static readonly layer = this.toLayer(({ competition }) => fetching(() => api.leagues(competition)));
}

export class GetSettings extends Query.Service<GetSettings>()("api/Settings", {
  success: wire<Answer<typeof api.settings>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api],
}) {
  static readonly layer = this.toLayer(() => fetching(api.settings));
}

/**
 * How a platform's login is going. Asked again every second and a half while
 * it runs, since authorizing is a browser tab and a person, not one request.
 */
export class GetLoginState extends Query.Service<GetLoginState>()("api/LoginState", {
  args: { platform: Schema.String },
  success: wire<Answer<typeof api.loginState>>(),
  error: ApiError,
  staleTime: 0,
  refetchInterval: (result) =>
    result._tag === "Success" && result.value.status === "running" ? "1500 millis" : undefined,
}) {
  static readonly layer = this.toLayer(({ platform }) => fetching(() => api.loginState(platform)));
}

/** When a platform's browser sync last stored anything, and which leagues it holds. */
export class GetCaptureStatus extends Query.Service<GetCaptureStatus>()("api/CaptureStatus", {
  args: { platform: Schema.String },
  success: wire<Answer<typeof api.captureStatus>>(),
  error: ApiError,
  staleTime: FRESH,
  tags: [tags.api],
}) {
  static readonly layer = this.toLayer(({ platform }) => fetching(() => api.captureStatus(platform)));
}
