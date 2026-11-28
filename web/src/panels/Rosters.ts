import { Command, Router, UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { Cause, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { Drawers, DrawerState, playerDrawer } from "@/components/league/drawers";
import { LeagueHeader } from "@/components/league/page-header";
import { RosterTable, toOrder } from "@/components/league/rosters/roster-table";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { ExternalLink } from "@/components/ui/controls/external-link";
import { MARKER } from "@/components/ui/controls/tabs";
import { ToggleChip } from "@/components/ui/controls/toggle";
import { SortState } from "@/components/ui/data-table";
import { Label } from "@/components/ui/label";
import { ListCard, ListRow } from "@/components/ui/list";
import { CardNote, QueryState } from "@/components/ui/state";
import { Table, Td, Th } from "@/components/ui/table";
import type { ApiError } from "@/lib/api";
import { Clickable } from "@/lib/clickable";
import { signed } from "@/lib/format";
import { GetOutlook, GetRoster, GetTeamRoster, GetUntouchables, ListTeams } from "@/lib/queries/teams";
import { AppRoute } from "@/lib/route";
import type { Competition, League, Outlook, TeamRef } from "@/lib/types";
import { wire } from "@/lib/wire";

const RostersPanelMessage = UiSchema.TaggedEnum({
  ClickedTeam: { team: wire<TeamRef>() },
  ClickedSortHeader: { sort: Schema.NullOr(SortState) },
  ClickedPlayer: { id: Schema.String },
  RequestedOpenDrawers: { open: DrawerState },
  RequestedCloseDrawers: {},
});

/** The team the address asks for (`?team=4`), where the route carries one. */
export const askedTeam = (route: AppRoute): string | undefined =>
  route._tag === "Competition" || route._tag === "League" || route._tag === "View" ? route.search.team : undefined;

/** The team shown: the one asked for, else yours, once the teams are in. */
function selectedTeam(teams: AsyncResult.AsyncResult<readonly TeamRef[], ApiError>, route: AppRoute) {
  if (!AsyncResult.isSuccess(teams)) return undefined;

  const asked = askedTeam(route);

  return teams.value.find((t) => t.team_id === asked) ?? teams.value.find((t) => t.is_mine);
}

/**
 * Any roster in the league: yours by default, anyone's from the chips.
 *
 * The weeks coming and the squad itself, in the same columns for every team,
 * so another manager's short week reads as plainly as yours. Trades have a
 * page of their own. Any row opens. The team shown is in the address
 * (`?team=4`), so a roster opened from the league table can be linked.
 *
 * Yours is read as yours — the columns that say how a player fits your
 * lineup — and anybody else's as theirs; each keeps its own sort, as two
 * tables would.
 */
export const RostersPanel = Html.component({
  name: "RostersPanel",
  props: Schema.Struct({ competition: wire<Competition>(), league: wire<League>(), route: AppRoute }),
  model: Schema.Struct({
    drawer: Schema.NullOr(DrawerState),
    sorts: Schema.Struct({ mine: Schema.NullOr(SortState), theirs: Schema.NullOr(SortState) }),
  }),
  message: RostersPanelMessage,
  queries: {
    teams: {
      query: ListTeams,
      args: ({ props }) => ({ competition: props.competition.key, league: props.league.league_id }),
    },
    mine: {
      query: GetRoster,
      args: ({ props, model, queries }) =>
        yours(selectedTeam(queries.teams, props.route))
          ? { competition: props.competition.key, league: props.league.league_id, ...toOrder(model.sorts.mine) }
          : undefined,
    },
    theirs: {
      query: GetTeamRoster,
      args: ({ props, model, queries }) => {
        const selected = selectedTeam(queries.teams, props.route);

        return selected === undefined || yours(selected)
          ? undefined
          : {
              competition: props.competition.key,
              league: props.league.league_id,
              team: selected.team_id,
              ...toOrder(model.sorts.theirs),
            };
      },
    },
    untouchables: {
      query: GetUntouchables,
      args: ({ props, queries }) =>
        yours(selectedTeam(queries.teams, props.route))
          ? { competition: props.competition.key, league: props.league.league_id }
          : undefined,
    },
    // Asked once the roster is in, as the card it fills sits beside it.
    outlook: {
      query: GetOutlook,
      args: ({ props, queries }) => {
        const selected = selectedTeam(queries.teams, props.route);
        const roster = yours(selected) ? queries.mine : queries.theirs;

        return props.competition.plans_weeks && AsyncResult.isSuccess(roster)
          ? {
              competition: props.competition.key,
              league: props.league.league_id,
              team: yours(selected) || selected === undefined ? "" : selected.team_id,
            }
          : undefined;
      },
    },
  },
}).make({
  init: () => ({ drawer: null, sorts: { mine: null, theirs: null } }),
  update: {
    // Yours clears the address's team rather than naming it: the page's own default.
    ClickedTeam: ($, { team }) =>
      $.run(
        Router.PatchSearch.make({
          route: $.props.route,
          patch: { team: team.is_mine ? undefined : team.team_id },
          history: "push",
          scroll: false,
        }).pipe(Command.asNoop),
      ).viewTransition([MARKER]),
    ClickedSortHeader: ($, { sort }) =>
      $.evolve({
        sorts: (sorts) =>
          yours(selectedTeam($.queries.teams, $.props.route)) ? { ...sorts, mine: sort } : { ...sorts, theirs: sort },
      }),
    ClickedPlayer: ($, { id }) => $.evolve({ drawer: playerDrawer(id) }),
    RequestedOpenDrawers: ($, { open }) => $.evolve({ drawer: open }),
    RequestedCloseDrawers: ($) => $.evolve({ drawer: null }),
  },
  view: (h, model) => {
    const { competition, league } = h.props;
    const teams = AsyncResult.isSuccess(h.queries.teams) ? h.queries.teams.value : [];
    const selected = selectedTeam(h.queries.teams, h.props.route);
    const mine = yours(selected);
    const roster = mine ? h.queries.mine : h.queries.theirs;
    const untouchables = AsyncResult.isSuccess(h.queries.untouchables) ? h.queries.untouchables.value.player_ids : [];
    const open = (id: string) => RostersPanelMessage.ClickedPlayer({ id });

    return h.div.class("contents").children(
      LeagueHeader(h, { competition, league }),
      teams.length > 1 &&
        h.div.class("flex flex-wrap gap-1.5 px-5 pt-5").children(
          teams.map((t) =>
            ToggleChip(h, {
              pressed: t.team_id === selected?.team_id,
              onClick: RostersPanelMessage.ClickedTeam({ team: t }),
              group: "rosters-team",
            })
              .key(t.team_id)
              .children(
                h.span.class("max-w-[14rem] truncate").children(t.name),
                t.is_mine && h.span.class("font-mono text-[10px] uppercase tracking-[0.08em] opacity-70").children("you"),
              ),
          ),
        ),

      QueryState(h, roster, { lines: 5 }),

      AsyncResult.isSuccess(roster) &&
        h.div.class("flex flex-col gap-4 p-5").children(
          competition.plans_weeks && WeeksAhead(h, { outlook: h.queries.outlook, onOpen: open }),
          Card(h).children(
            CardHeader(h).children(
              h.span.class("flex items-center gap-1").children(
                selected?.name ?? "Squad",
                selected !== undefined &&
                  !mine &&
                  ExternalLink(h, {
                    key: "team",
                    props: { href: selected.url, label: `Open ${selected.name} on the platform` },
                  }),
              ),
              h.span(`${roster.value.length} players`),
            ),
            RosterTable(h, {
              players: [...roster.value],
              empty: { title: "No players" },
              onOpen: open,
              sort: mine ? model.sorts.mine : model.sorts.theirs,
              onSort: (sort) => RostersPanelMessage.ClickedSortHeader({ sort }),
              untouchable: mine ? (id) => untouchables.includes(id) : undefined,
            }),
          ),
        ),
      Drawers(h, {
        props: { competition: competition.key, league: league.league_id, open: model.drawer },
        onEmit: {
          RequestedOpen: ({ open }) => RostersPanelMessage.RequestedOpenDrawers({ open }),
          RequestedClose: () => RostersPanelMessage.RequestedCloseDrawers(),
        },
      }),
    );
  },
});

/** Whether the team shown is yours: it is, until the teams say otherwise. */
function yours(selected: TeamRef | undefined): boolean {
  return selected === undefined || selected.is_mine;
}

/**
 * The next few weeks as the roster stands.
 *
 * A week where byes and injuries land together is a loss that can be seen a
 * month out, and a pickup made then costs a bench spot rather than whatever
 * is left on the morning. Only a week with something to say is listed —
 * somebody missing, a regular with few games, a heavy week, one short enough
 * to act on — with the pickup that fixes it where one does; a stretch with
 * nothing to say is one line, not a row a week saying so. A week the league
 * has yet to finish scheduling is provisional: its count is a floor. A week
 * counts projected points, or in basketball the games the daily lineups can start.
 */
function WeeksAhead<M>(
  h: Html.H<M>,
  { outlook, onOpen }: { outlook: AsyncResult.AsyncResult<Outlook, ApiError>; onOpen: (id: string) => M },
) {
  const data = AsyncResult.isSuccess(outlook) ? outlook.value : null;

  // A competition that reads its weeks ahead as fixtures — FPL — sends a grid instead of weeks.
  if (data !== null && data.run_weeks.length > 0) {
    const runs = data.runs;

    return ListCard(h, {
      title: "Weeks ahead",
      count: runs.length ? `${runs.length} to watch` : undefined,
      children: [FixtureGrid(h, { outlook: data, onOpen })],
    });
  }

  const weeks = data?.weeks;

  const flagged = weeks?.filter(
    (w) => w.missing.length > 0 || w.light.length > 0 || w.short || w.heavy || w.provisional || w.fix,
  );

  const short = weeks?.filter((w) => w.short).length ?? 0;
  const usual = data?.usual;
  const games = data?.measure === "games";
  const last = weeks?.at(-1);
  // Games are whole; a usual week of them is a median, which can fall between two.
  const figure = (value: number) => (games ? `${Number(value.toFixed(1))} games` : `${value.toFixed(1)} proj`);

  return ListCard(h, {
    title: "Weeks ahead",
    count: short ? `${short} short` : usual != null ? `usual week ${figure(usual)}` : undefined,
    loading: AsyncResult.isInitial(outlook),
    error: AsyncResult.isFailure(outlook) ? Cause.squash(outlook.cause) : null,
    children: [
      weeks?.length === 0 && CardNote(h).children("No weeks left."),
      last !== undefined && flagged?.length === 0 && CardNote(h).children(`Nothing to flag through week ${last.week}.`),
      // Spread rather than nested: a run of rows nested among its siblings tripped the patch as the card filled in.
      ...(flagged ?? []).map((week) =>
        ListRow(h, { class: "flex-col items-stretch gap-1" })
          .key(String(week.week))
          .children(
            h.div.class("flex items-baseline gap-3").children(
              Label(h, { class: "w-20 shrink-0" }).children(`Week ${week.week}`),
              h.span
                .class("min-w-0 flex-1 truncate text-muted-foreground")
                .children(week.missing.length ? `Without ${week.missing.join(", ")}` : "Everyone available"),
              h.span.class("shrink-0 font-mono text-[12px] tabular-nums").children(figure(week.points)),
              // Said in words as well as tinted.
              week.provisional && Badge(h, { variant: "warn", appearance: "pill", class: "shrink-0" }).children("provisional"),
              week.heavy && Badge(h, { variant: "ok", appearance: "pill", class: "shrink-0" }).children("heavy"),
              week.short &&
                Badge(h, { variant: "fail", appearance: "pill", class: "shrink-0" }).children(
                  `short ${Number(week.short_by.toFixed(1))}`,
                ),
            ),
            week.light.length > 0 &&
              h.p.class("pl-[5.75rem] text-[12.5px] text-muted-foreground").children(`Light: ${week.light.join(", ")}`),
            week.fix &&
              h.p
                .class("pl-[5.75rem] text-[12.5px]")
                .children(
                  `${week.fix} `,
                  h.span
                    .class("font-mono text-muted-foreground")
                    .children(`(${games ? `${signed(week.gain, 0)} games` : signed(week.gain)})`),
                ),
          ),
      ),
    ],
  });
}

/** FPL's 1-5 fixture difficulty as a badge's tone; the number is printed too, so it is not color alone. */
function difficultyTone(difficulty: number): "ok" | "muted" | "warn" | "fail" {
  return difficulty <= 2 ? "ok" : difficulty === 3 ? "muted" : difficulty === 4 ? "warn" : "fail";
}

/**
 * Each listed player's next gameweeks, a column a week: opponent, home or away,
 * and difficulty. Only a player with something to act on gets a row — a blank,
 * a double, a hard run, a doubt — and the weeks a blank or double lands on the
 * squad are named above; everybody else is one line.
 */
function FixtureGrid<M>(h: Html.H<M>, { outlook, onOpen }: { outlook: Outlook; onOpen: (id: string) => M }) {
  const weeks = outlook.run_weeks;
  const last = weeks.at(-1);

  // Spread rather than nested: a run of rows nested among its siblings tripped the patch as the card filled in.
  return h.div.class("contents").children(
    ...outlook.warnings.map((w) =>
      ListRow(h, { class: "items-baseline gap-3" })
        .key(`${w.label}-${w.value}`)
        .children(
          Label(h, { class: "w-20 shrink-0" }).children(w.label),
          h.span
            .attr("class", w.tone === "warning" ? "text-warn" : w.tone === "good" ? "text-ok" : undefined)
            .children(w.value),
        ),
    ),
    outlook.runs.length > 0 &&
      Table(h).children(
        h.thead.children(
          h.tr.children(
            Th(h).children("Player"),
            weeks.map((week) =>
              Th(h, "px-2 text-center")
                .key(String(week))
                .children(`GW${week}`),
            ),
          ),
        ),
        h.tbody.children(
          outlook.runs.map((run) =>
            Clickable(h, "tr", onOpen(run.player_id), { role: null })
              .key(run.player_id)
              .class("cursor-pointer hover:bg-muted/50")
              .children(
                Td(h).children(
                  h.div.class("font-medium").children(run.player),
                  h.div.class("text-[11.5px] text-muted-foreground").children(`${run.detail} · ${run.flags.join(" · ")}`),
                ),
                run.weeks.map((week) =>
                  Td(h, "px-2")
                    .key(String(week.week))
                    .children(
                      h.div.class("flex flex-col items-center gap-1").children(
                        week.games.length === 0
                          ? Badge(h, { variant: "fail" }).children("blank")
                          : week.games.map((game, i) =>
                              Badge(h, { variant: difficultyTone(game.difficulty) })
                                .key(String(i))
                                .children(`${game.opponent} ${game.home ? "H" : "A"} ${game.difficulty}`),
                            ),
                      ),
                    ),
                ),
              ),
          ),
        ),
      ),
    outlook.clear > 0 &&
      CardNote(h).children(
        `${outlook.runs.length ? `${outlook.clear} others` : `All ${outlook.clear}`}: no blanks, doubles or hard runs through GW${last}.`,
      ),
  );
}
