/**
 * A failure, and the one thing this app can do about it.
 *
 * The server says both: the condition in words, and the remedy — the same one
 * a terminal prints as a command — so nothing here decides what fixes what.
 */
import { Command, Component, Router, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Effect, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { buttonVariants } from "@/components/ui/controls/button";
import { Icon } from "@/components/ui/icon";
import { ApiError, api } from "@/lib/api";
import { GetLoginState } from "@/lib/queries/app";
import { fetching, tags } from "@/lib/queries/cache";
import { AppRoute } from "@/lib/route";
import type { Remedy } from "@/lib/types";
import { cn } from "@/lib/utils";
import { wire } from "@/lib/wire";

const RemedyMessage = UiSchema.TaggedEnum({
  ClickedSettings: {},
  ClickedRetry: {},
  ClickedLogin: {},
  SucceededStartLogin: {},
  FailedStartLogin: {},
  /** What the login query holds now: its status, or null while it has none. */
  ChangedLoginState: { status: Schema.NullOr(Schema.String) },
});

/**
 * Everything asked again: whatever else failed on this page failed on the
 * same outage, or on the authorization that now exists.
 */
class AskAgain extends Command.Service<AskAgain>()("remedy/AskAgain", { invalidates: () => [tags.api] }) {
  static readonly layer = this.toLayer(() => Effect.void);
}

/** Starts a platform's login. Authorizing is a browser tab and a person, so the server reports progress separately. */
class StartLogin extends Command.Service<StartLogin>()("remedy/StartLogin", {
  args: { platform: Schema.String },
  success: RemedyMessage,
}) {
  static readonly layer = this.toLayer(({ platform }) =>
    fetching(() => api.login(platform)).pipe(
      Effect.match({
        onSuccess: () => RemedyMessage.SucceededStartLogin(),
        onFailure: () => RemedyMessage.FailedStartLogin(),
      }),
    ),
  );
}

const outline = buttonVariants({ variant: "outline" });

/** The control a remedy asks for: a login, Settings, another try, or a page off the app. */
const RemedyActionNoDeps = Html.component({
  name: "RemedyAction",
  props: Schema.Struct({ remedy: wire<Remedy>() }),
  model: Schema.Struct({ watching: Schema.Boolean }),
  message: RemedyMessage,
  queries: {
    login: {
      query: GetLoginState,
      args: ({ props, model }) =>
        model.watching && props.remedy.action === "authorize" ? { platform: props.remedy.platform } : undefined,
      onChange: (result) =>
        RemedyMessage.ChangedLoginState({ status: AsyncResult.isSuccess(result) ? result.value.status : null }),
    },
  },
  restore: false,
}).make({
  init: () => ({ watching: false }),
  update: {
    ClickedSettings: ($) => $.run(Router.push(AppRoute, AppRoute.Settings()).pipe(Command.asNoop)),
    ClickedRetry: ($) => $.run(AskAgain.make({})),
    ClickedLogin: ($) => $.run(StartLogin.make({ platform: $.props.remedy.platform })),
    SucceededStartLogin: ($) => $.evolve({ watching: true }),
    FailedStartLogin: ($) => $.model,
    // Everything about this competition failed on the missing authorization;
    // none of those answers are worth keeping now that it exists. Polling
    // stops on its own once the status is no longer running.
    ChangedLoginState: ($, { status }) => (status === "ok" ? $.run(AskAgain.make({})) : $.model),
  },
  view: (h) => {
    const { remedy } = h.props;


    switch (remedy.action) {
      case "authorize": {
        const state = AsyncResult.isSuccess(h.queries.login) ? h.queries.login.value : null;
        const running = h.isRunning(StartLogin) || state?.status === "running";

        return h.div.class("flex flex-col gap-2").children(
          h.button
            .attrs({ type: "button", class: buttonVariants({ variant: "primary" }) })
            .disabled(running)
            .on("click", RemedyMessage.ClickedLogin())
            .children(running ? "Waiting for the browser…" : remedy.label),
          running &&
            h.p
              .class("max-w-[60ch] text-[12.5px] text-muted-foreground")
              .children("Approve the app in the new tab. Accept any certificate warning."),
          state?.status === "failed" &&
            h.p.class("max-w-[70ch] text-[12.5px] leading-relaxed text-destructive").children(state.detail),
        );
      }

      case "settings":
        return h.button
          .attrs({ type: "button", class: outline })
          .on("click", RemedyMessage.ClickedSettings())
          .children(remedy.label);
      case "retry":
        return h.button
          .attrs({ type: "button", class: outline })
          .on("click", RemedyMessage.ClickedRetry())
          .children(remedy.label);
      case "link":
        return h.a
          .attrs({ href: remedy.url, target: "_blank", rel: "noopener noreferrer", class: outline })
          .children(remedy.label, Icon(h, "external-link", { class: "size-3.5" }));
    }
  },
});

export const RemedyAction = RemedyActionNoDeps.pipe(Component.provide([AskAgain.layer, StartLogin.layer]));

/**
 * The failure, in the server's words, with what can be done about it.
 *
 * Inset by its own margin, for the common case of standing in for a page or a
 * card's contents; a caller placing it in a padded stack passes `m-0`. `key`
 * tells two of them in one view apart.
 */
export function ErrorNote<M>(
  h: Html.H<M>,
  { error, class: extra, key = "error" }: { error: unknown; class?: string | undefined; key?: string },
) {
  return h.div
    .attrs({
      role: "alert",
      class: cn(
        "m-5 flex flex-col items-start gap-3 rounded-md border border-destructive/30 bg-destructive/8 px-4 py-3",
        extra,
      ),
    })
    .children(
      h.p
        .class("max-w-[70ch] text-[13.5px] leading-relaxed text-destructive")
        .children(error instanceof Error ? error.message : "Something went wrong."),
      error instanceof ApiError && error.remedy !== null && RemedyAction(h, { key, props: { remedy: error.remedy } }),
    );
}
