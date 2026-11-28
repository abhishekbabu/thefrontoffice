import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Cause, Option, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { Badge } from "@/components/ui/badge";
import { ExternalLink } from "@/components/ui/controls/external-link";
import { RemedyAction } from "@/components/ui/error-note";
import { Icon } from "@/components/ui/icon";
import { Meta } from "@/components/ui/label";
import { ListCard, ListRow } from "@/components/ui/list";
import { CardNote } from "@/components/ui/state";
import { ListLeagues } from "@/lib/queries/app";
import type { Competition, League } from "@/lib/types";
import { wire } from "@/lib/wire";

const LandingMessage = UiSchema.TaggedEnum({
  ClickedLeague: { competition: wire<Competition>(), league: wire<League>() },
});

/** `Picked`: the league chosen, with the competition it is in. The shell opens it. */
export const LandingEvents = UiSchema.TaggedEnum({
  Picked: { competition: wire<Competition>(), league: wire<League>() },
});

/**
 * What the app opens on: every league you are in, across every competition.
 *
 * The alternative — dropping straight into whichever competition happened to be
 * configured first — silently picks for you, and with three competitions and several
 * leagues each it is picking wrong most of the time.
 */
export const Landing = Html.component({
  name: "Landing",
  props: Schema.Struct({ competitions: wire<Competition[]>() }),
  model: Schema.Null,
  message: LandingMessage,
  events: LandingEvents,
  queries: {
    // One query per competition rather than one combined endpoint: they fail
    // independently — one platform being down must not take the page down — and
    // each is the entry the panels already read. A competition that is
    // blocked is not asked at all; the request could only fail, and the reason
    // is already known.
    leagues: {
      queryMany: ListLeagues,
      args: ({ props }) =>
        props.competitions
          .filter((competition) => competition.configured && !competition.blocked)
          .map((competition) => ({ competition: competition.key })),
    },
  },
}).make({
  init: () => null,
  update: {
    ClickedLeague: ($, { competition, league }) => $.emit(LandingEvents.Picked({ competition, league })),
  },
  view: (h) => {
    const { competitions } = h.props;
    const configured = competitions.filter((competition) => competition.configured);
    const missing = competitions.filter((competition) => !competition.configured);

    const card = (competition: Competition) => {
      const result = competition.blocked
        ? AsyncResult.initial()
        : Option.match(h.queries.leagues.get({ competition: competition.key }), {
            onNone: () => AsyncResult.initial(),
            onSome: (entry) => entry.result,
          });

      const leagues = AsyncResult.isSuccess(result) ? result.value : null;

      return h.div.key(competition.key).class("animate-list-item").children(
        ListCard(h, {
          title: competition.label,
          count: leagues === null ? undefined : `${leagues.length} ${leagues.length === 1 ? "league" : "leagues"}`,
          aside: competition.blocked ? [Badge(h, { variant: "warn", appearance: "status" }).children("unavailable")] : undefined,
          loading: !competition.blocked && AsyncResult.isInitial(result),
          // Shown in place rather than as a page-level failure: the other
          // competitions are still usable, and this one names its own fix.
          error: AsyncResult.isFailure(result) ? Cause.squash(result.cause) : null,
          children: [
            // Stated once, with the action, rather than left to fail on the
            // first click into the competition.
            competition.blocked &&
              h.div.class("flex flex-col items-start gap-3 px-4 py-3").children(
                h.p.class("max-w-[70ch] text-[13px] leading-relaxed text-muted-foreground").children(competition.blocked.detail),
                competition.blocked.remedy &&
                  RemedyAction(h, { key: competition.key, props: { remedy: competition.blocked.remedy } }),
              ),
            leagues !== null && leagues.length === 0 && CardNote(h).children("No leagues this season."),
            ...(leagues ?? []).map((league) => row(competition, league)),
          ],
        }),
      );
    };

    // A row, not a button: the way across to the platform sits inside it, and
    // a link inside a button is two controls a screen reader and a keyboard
    // cannot tell apart. The button's hit area is stretched over the row
    // instead, with the link raised above it.
    const row = (competition: Competition, league: League) =>
      ListRow(h, { class: "relative items-center py-3 transition-colors hover:bg-muted motion-reduce:transition-none" })
        .key(league.league_id)
        .children(
          h.button
            .attrs({ type: "button", class: "min-w-0 flex-1 text-left after:absolute after:inset-0 after:content-['']" })
            .on("click", LandingMessage.ClickedLeague({ competition, league }))
            .children(
              h.div.class("truncate font-display text-[15px] font-semibold tracking-tight").children(league.name),
              league.detail && Meta(h, { as: "div", class: "mt-0.5 truncate" }).children(league.detail),
            ),
          // Straight to the platform, for when you already know what you came
          // to do and this app is not it.
          ExternalLink(h, {
            key: `${competition.key}/${league.league_id}`,
            props: { href: league.url, label: `Open ${league.name} on the platform`, class: "relative z-10" },
          }),
          Icon(h, "chevron-right", { class: "size-4 shrink-0 text-muted-foreground" }),
        );

    return h.div.class("mx-auto max-w-3xl px-6 py-10").children(
      h.div.class("flex items-center gap-3").children(
        h.span
          .class("flex size-9 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground")
          .children(Icon(h, "trophy", { class: "size-5", strokeWidth: 2.25 })),
        h.div(
          h.h1.class("font-display text-2xl font-semibold tracking-tight").children("The Front Office"),
          h.p.class("font-mono text-[12px] text-muted-foreground").children("Pick a league"),
        ),
      ),
      h.div.class("mt-8 flex flex-col gap-4").children(configured.map(card)),
      missing.length > 0 &&
        h.p
          .class("mt-6 text-[13px] text-muted-foreground")
          .children(
            `${missing.map((competition) => competition.label).join(" and ")} ${missing.length === 1 ? "is" : "are"} not configured. Add credentials in Settings.`,
          ),
    );
  },
});
