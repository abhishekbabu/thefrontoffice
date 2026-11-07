/**
 * Generated from the API's OpenAPI schema by `just api-types`. Do not edit:
 * change the Python models, then regenerate. `just check-web` fails on drift.
 */

export interface paths {
    "/api/competitions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Sports
         * @description Every competition, including ones this machine has no credentials for.
         *
         *     Unconfigured ones are returned rather than hidden so the UI can say
         *     what to set instead of silently offering less than it could.
         */
        get: operations["list_sports_api_competitions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/capabilities": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Capabilities
         * @description What this installation can actually do.
         *
         *     Read before anything is offered. Without a key there is no analysis to
         *     give, so nothing that needs one is shown — rather than shown and then
         *     refused, which is a click spent learning the app cannot do it.
         */
        get: operations["capabilities_api_capabilities_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Read Settings
         * @description Every configurable value, with secrets reported as present or absent.
         *
         *     A secret's contents never leave the process. There is nothing the UI can
         *     do with the characters of an API key that it cannot do with the fact
         *     that one is set, and a page that renders them puts them in screenshots.
         */
        get: operations["read_settings_api_settings_get"];
        /**
         * Save Settings
         * @description Write values to .env and re-read configuration into the running app.
         *
         *     Rejects any key no setting reads rather than writing it: a line nothing
         *     picks up looks saved and changes nothing, which is the exact failure
         *     this endpoint exists to prevent.
         */
        put: operations["save_settings_api_settings_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/yahoo/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Yahoo Login State */
        get: operations["yahoo_login_state_api_yahoo_login_get"];
        put?: never;
        /**
         * Start Yahoo Login
         * @description Begin the handshake and return at once.
         *
         *     The browser tab it opens is on this machine — the server and the person
         *     are the same place — but the click cannot be waited on inside a request,
         *     so progress is reported through the companion GET.
         */
        post: operations["start_yahoo_login_api_yahoo_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Leagues */
        get: operations["list_leagues_api__competition__leagues_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/roster": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Roster
         * @description One card per player, with per-competition columns rendered generically.
         *
         *     The columns are the competition's own vocabulary — FPL sends Price and xGI,
         *     football sends Depth — so the client reads whatever keys arrive rather
         *     than being taught each competition.
         */
        get: operations["roster_api__competition__leagues__league_id__roster_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/players/{player_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Player
         * @description Everything worth knowing about one player, when someone asks.
         */
        get: operations["player_api__competition__leagues__league_id__players__player_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Summary
         * @description Where the team stands, before any report is asked for.
         *
         *     The page would otherwise be blank for as long as a model call takes,
         *     showing nothing the app already knows. To-do items carry what the
         *     manager decided about them — dismissed, snoozed, or back since.
         */
        get: operations["summary_api__competition__leagues__league_id__summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/items": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Decide
         * @description Dismiss, snooze or restore one to-do item; the decision kept, or null once restored.
         */
        post: operations["decide_api__competition__leagues__league_id__items_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/free-agents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Free Agents
         * @description One page of who is still out there, best first.
         *
         *     Ordering happens here rather than in the client because a football pool
         *     is four thousand players: a client holding fifty of them can only
         *     reorder those fifty, which is a worse answer than none.
         */
        get: operations["free_agents_api__competition__leagues__league_id__free_agents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/teams": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Teams
         * @description Everyone in the league, so their rosters can be opened.
         */
        get: operations["teams_api__competition__leagues__league_id__teams_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/teams/{team_id}/roster": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Team Roster
         * @description Somebody else's squad, in the same columns as your own.
         */
        get: operations["team_roster_api__competition__leagues__league_id__teams__team_id__roster_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/schedule": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Schedule
         * @description The league beyond this week: the season, the table, the real games.
         *
         *     Separate from `summary` because it answers a different question and
         *     costs requests the week does not need — nobody checking their lineup
         *     should wait on the whole season's fixtures.
         */
        get: operations["schedule_api__competition__leagues__league_id__schedule_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/weeks-ahead": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Weeks Ahead
         * @description The next few weeks as your roster stands, and a pickup for any that comes up short.
         *
         *     Empty where a competition cannot project its weeks ahead: there is
         *     nothing to plan, which is an answer rather than a failure.
         */
        get: operations["weeks_ahead_api__competition__leagues__league_id__weeks_ahead_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/trades": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Trades
         * @description The trades that would most raise your playoff chance and that the other side gains from too.
         *
         *     Its own route because it plays the season out once per trade tried —
         *     seconds, not the instant a table should take to appear.
         */
        get: operations["trades_api__competition__leagues__league_id__trades_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/scout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Scout
         * @description Judge the week's to-do list — or return the kept judgment where nothing has changed.
         */
        post: operations["scout_api__competition__leagues__league_id__scout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/judgment": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Judgment
         * @description The league's last judgment, or null — read without asking the model anything.
         *
         *     What lets the week show its verdicts on load: judging is a click,
         *     and a reload should not throw the answer away.
         */
        get: operations["judgment_api__competition__leagues__league_id__judgment_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/threads": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Thread
         * @description Open a conversation about one to-do item or one player.
         *
         *     Seeded with that subject alone, so a question about Hall's row is
         *     answered about Hall's row; the turns then go through the chat endpoint
         *     like any other conversation.
         */
        post: operations["thread_api__competition__leagues__league_id__threads_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/free-agents/judge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Judge Free Agents
         * @description A call on each of the free agents on screen, to show on their rows.
         */
        post: operations["judge_free_agents_api__competition__leagues__league_id__free_agents_judge_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/{competition}/leagues/{league_id}/free-agents/calls": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Free Agent Calls
         * @description The kept call on each free agent on screen, without asking the model anything.
         *
         *     What lets the wire show its calls on load. A player whose situation
         *     has moved since his call comes back marked stale.
         */
        post: operations["free_agent_calls_api__competition__leagues__league_id__free_agents_calls_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/chat/{chat_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Ask
         * @description Ask the next question in a conversation a thread opened.
         */
        post: operations["ask_api_chat__chat_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * Action
         * @description One decision the week asks of the manager, and why it is one.
         *
         *     Computed from league state, never by a model: a starter ruled out or a slot
         *     left empty is a fact, and the list has to be right before anything is
         *     asked to judge it.
         */
        Action: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "lineup" | "waiver" | "trade";
            /**
             * Urgency
             * @enum {string}
             */
            urgency: "now" | "soon" | "later";
            /**
             * Key
             * @description Which decision this is — the hole it fills or the swap it makes — stable while the decision stays the same one, so a verdict finds its row again.
             * @default
             */
            key: string;
            /**
             * Title
             * @description The move, as an instruction: 'Start Jordyn Tyson over Chris Olave'.
             */
            title: string;
            /**
             * Reason
             * @description Why, in the league's own facts: 'Olave is ruled out. +11.2 proj pts'.
             */
            reason: string;
            /**
             * When
             * @description The deadline, as a label: 'before kickoff, Thu 22 Oct', 'week 8'. Empty when the platform publishes none — a guessed deadline is worse than no deadline.
             * @default
             */
            when: string;
            /**
             * Player Id
             * @description The player the move turns on, to open their detail.
             * @default
             */
            player_id: string;
            /**
             * Replaces
             * @description The player the move takes out of the lineup, by id — empty where it fills an empty slot or moves nobody. With `player_id`, what the move does to a lineup.
             * @default
             */
            replaces: string;
            /**
             * Drop
             * @description For a pickup, who to release to make room, by id — empty where the roster has a spot open, or the move adds nobody.
             * @default
             */
            drop: string;
            /**
             * Win Change
             * @description How much the move changes the chance of winning this week, from simulating the matchup — 0.028 for +2.8 points of probability.
             */
            win_change: number | null;
            /**
             * Evidence
             * @description What the move rests on beyond the projection, one line per player it involves — the matchup and the role behind the number. Empty where nothing has been played yet.
             */
            evidence: components["schemas"]["Stat"][];
            /** @description The model's judgement, once a report has been run. None before, and for an item it skipped. */
            verdict: components["schemas"]["TaskVerdict"] | null;
            /**
             * Hidden
             * @description Hidden by the manager's own decision: dismissed, or snoozed for now.
             */
            hidden: ("dismissed" | "snoozed") | null;
            /**
             * Snoozed Until
             * @description When a snooze runs out.
             */
            snoozed_until: string | null;
            /**
             * Resurfaced
             * @description Whether a dismissed item has changed since, and so is back.
             * @default false
             */
            resurfaced: boolean;
            /** @description `win_change` as it reads — '+2.8% to win', toned by its sign. Written where the week is presented, so a page and a terminal say it alike; None where unpriced. */
            chance: components["schemas"]["Stat"] | null;
            /**
             * Fingerprint
             * @description What this item currently says, so a verdict on an older version of it reads as stale.
             *
             *     Everything a judgement rested on and nothing it produced: the move,
             *     the reason, the deadline and the evidence — not the verdict itself.
             */
            readonly fingerprint: string;
        };
        /**
         * ActivityRow
         * @description One thing somebody in the league did.
         */
        ActivityRow: {
            /**
             * When
             * @description Already formatted; a raw epoch is not a date.
             * @default
             */
            when: string;
            /**
             * Who
             * @description The manager, not the roster id.
             * @default
             */
            who: string;
            /**
             * What
             * @description Add, drop, trade, waiver — in the platform's own vocabulary.
             */
            what: string;
            /**
             * Detail
             * @description The players involved.
             * @default
             */
            detail: string;
            /**
             * Is Mine
             * @default false
             */
            is_mine: boolean;
        };
        /**
         * CallsRequest
         * @description The free agents on screen, whose kept calls to show.
         */
        CallsRequest: {
            /** Player Ids */
            player_ids: string[];
        };
        /**
         * Capabilities
         * @description What the app can do here, as opposed to what it knows how to do.
         */
        Capabilities: {
            /** Ai */
            ai: boolean;
            limits: components["schemas"]["Limits"];
        };
        /** ChatRequest */
        ChatRequest: {
            /** Message */
            message: string;
        };
        /**
         * Competition
         * @description One registry entry as the picker sees it: who it is, what it can do, and whether it can be opened.
         */
        Competition: {
            /** Key */
            key: string;
            /** Sport */
            sport: string;
            /** Competition */
            competition: string;
            /** Platform */
            platform: string;
            /** Label */
            label: string;
            /** Name */
            name: string;
            /** Judges Wire */
            judges_wire: boolean;
            /** Plans Ahead */
            plans_ahead: boolean;
            /** Configured */
            configured: boolean;
            /** Requires */
            requires: string;
            /** Ready */
            ready: boolean;
            /**
             * Blocked Reason
             * @default
             */
            blocked_reason: string;
            /** Blocked Code */
            blocked_code: ("error" | "platform_unavailable" | "unknown_competition" | "not_configured" | "unsupported" | "subject_gone" | "item_decision" | "ai_unavailable" | "ai_key_invalid" | "ai_quota" | "ai_failed" | "login_required" | "access_not_approved") | null;
            blocked_remedy: components["schemas"]["Remedy"] | null;
        };
        /**
         * ErrorBody
         * @description A failure the user can read, and what can be done about it.
         */
        ErrorBody: {
            /** Detail */
            detail: string;
            /**
             * Code
             * @enum {string}
             */
            code: "error" | "platform_unavailable" | "unknown_competition" | "not_configured" | "unsupported" | "subject_gone" | "item_decision" | "ai_unavailable" | "ai_key_invalid" | "ai_quota" | "ai_failed" | "login_required" | "access_not_approved";
            remedy: components["schemas"]["Remedy"] | null;
        };
        /**
         * Forecast
         * @description The week played many times over, and what each move does to it.
         */
        Forecast: {
            /**
             * Win
             * @description Chance of winning, a tie counting half.
             */
            win: number;
            margin: components["schemas"]["MarginRange"];
            /** Simulations */
            simulations: number;
            /**
             * Moves
             * @description Each move's key, and the chance of winning with it.
             */
            moves: {
                [key: string]: number;
            };
            /**
             * Best Move
             * @description The move that most raises the chance, if any does; empty otherwise.
             * @default
             */
            best_move: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail: components["schemas"]["ValidationError"][];
        };
        /**
         * ItemDecision
         * @description One decision about one to-do item, as the page sends it.
         */
        ItemDecision: {
            /** Key */
            key: string;
            /**
             * Decision
             * @enum {string}
             */
            decision: "dismiss" | "snooze" | "restore";
            /**
             * Fingerprint
             * @description For dismiss: the item as it read when dismissed.
             * @default
             */
            fingerprint?: string;
            /**
             * Until
             * @description For snooze: when it comes back, with its offset.
             */
            until?: string | null;
        };
        /**
         * ItemState
         * @description What the manager has decided about one to-do item.
         *
         *     Dismissed against a fingerprint rather than for good: "not this" is a
         *     judgment about the item as it read, and an item that changes — new news,
         *     a different gain — is new information, which brings it back.
         */
        ItemState: {
            /** Key */
            key: string;
            /**
             * Dismissed As
             * @description The fingerprint the item had when dismissed; empty if not.
             * @default
             */
            dismissed_as: string;
            /**
             * Snoozed Until
             * @description Hidden until then, aware UTC; None if not.
             */
            snoozed_until: string | null;
        };
        /**
         * JudgeRequest
         * @description The free agents on screen to judge, best first.
         */
        JudgeRequest: {
            /** Player Ids */
            player_ids: string[];
        };
        /**
         * LeagueRef
         * @description A league the user is in, in whatever platform the competition uses.
         */
        LeagueRef: {
            /** League Id */
            league_id: string;
            /** Name */
            name: string;
            /**
             * Detail
             * @default
             */
            detail: string;
            /**
             * Url
             * @default
             */
            url: string;
        };
        /**
         * LeagueSchedule
         * @description The league beyond this week: where the season goes, and where you sit.
         *
         *     Every section is optional because the platforms genuinely differ — a
         *     classic FPL league has a table and no head-to-head season, and FPL has no
         *     transaction feed at all. An empty section renders as nothing rather than as
         *     an empty promise.
         */
        LeagueSchedule: {
            /**
             * Headline
             * @description Your season in figures: record, place, points, playoff chance.
             */
            headline: components["schemas"]["Stat"][];
            /** Season */
            season: components["schemas"]["ScheduleRow"][];
            /** Standings */
            standings: components["schemas"]["StandingRow"][];
            /** Matches */
            matches: components["schemas"]["Match"][];
            /** Activity */
            activity: components["schemas"]["ActivityRow"][];
        };
        /**
         * Limits
         * @description The engines' own bounds, sent so the page can say them rather than restate them.
         */
        Limits: {
            /**
             * Judged
             * @description How many free agents one judging asks about: a screen's worth of the best.
             */
            judged: number;
            /**
             * Trade Change
             * @description The least a trade must raise your playoff chance to be offered, as a fraction: 0.005.
             */
            trade_change: number;
        };
        /**
         * LoginState
         * @description Where the Yahoo handshake has got to.
         */
        LoginState: {
            /**
             * Status
             * @enum {string}
             */
            status: "idle" | "running" | "ok" | "failed";
            /**
             * Detail
             * @default
             */
            detail: string;
        };
        /**
         * MarginRange
         * @description How the margin falls across the simulated weeks: positive is a win.
         */
        MarginRange: {
            /**
             * Low
             * @description Tenth percentile: four weeks in five end above it.
             */
            low: number;
            /** Median */
            median: number;
            /**
             * High
             * @description Ninetieth percentile: four weeks in five end below it.
             */
            high: number;
        };
        /**
         * Match
         * @description One real-world game behind a fantasy week.
         *
         *     Distinct from a fantasy fixture: this is two actual clubs, on a date, and
         *     it is what a projection is a projection *about*.
         */
        Match: {
            /**
             * Label
             * @description When it kicks off, already formatted.
             * @default
             */
            label: string;
            /** Home */
            home: string;
            /** Away */
            away: string;
            /**
             * Detail
             * @description Difficulty, status, or whatever that competition reads off a fixture.
             * @default
             */
            detail: string;
            /**
             * Tone
             * @default neutral
             * @enum {string}
             */
            tone: "neutral" | "good" | "warning";
        };
        /**
         * Move
         * @description One recommended action on one player, as the model judged it.
         *
         *     How the model is asked to fill each field is `MoveAnswer`'s, in
         *     `application/formats.py`; this is what a report keeps and a page shows.
         */
        Move: {
            /**
             * Action
             * @enum {string}
             */
            action: "ADD" | "DROP" | "START" | "BENCH" | "TRANSFER" | "CAPTAIN" | "MONITOR";
            /** Player */
            player: string;
            /** Position */
            position: string;
            /** Team */
            team: string;
            /** Metric */
            metric: string;
            /** Rationale */
            rationale: string;
            /**
             * Replaces
             * @default
             */
            replaces: string;
            /**
             * Replaces Rationale
             * @default
             */
            replaces_rationale: string;
            /**
             * Title
             * @description The move as an instruction, the way a to-do item words its own: 'Add Warren, drop Johnson'.
             *
             *     Written here, once, so a page and a terminal phrase a move alike.
             */
            readonly title: string;
        };
        /**
         * PlayerCall
         * @description The model's call on one available player, shown on his row.
         *
         *     What the model writes is `CallAnswer`, in `application/formats.py`; the
         *     engine adds when it was made and whether it still stands.
         */
        PlayerCall: {
            /** Player Id */
            player_id: string;
            /**
             * Decision
             * @enum {string}
             */
            decision: "ADD" | "WATCH" | "PASS";
            /**
             * Drop
             * @default
             */
            drop: string;
            /** Reason */
            reason: string;
            /**
             * Judged At
             * @description When the call was made.
             */
            judged_at: string | null;
            /**
             * Stale
             * @description Whether the player's situation has changed since the call.
             * @default false
             */
            stale: boolean;
        };
        /**
         * PlayerCard
         * @description A player as a row in a roster table.
         *
         *     `columns` is the competition's own vocabulary — the Premier League sends
         *     Price and xPts, the NFL sends Slot — so a client renders whatever keys
         *     arrive rather than being taught each one. What sits beside it is what a
         *     table needs and a column should not be: an identifier to open, and whether
         *     the row wants attention.
         */
        PlayerCard: {
            /** Player Id */
            player_id: string;
            /** Columns */
            columns: {
                [key: string]: string;
            };
            /**
             * Values
             * @description The number behind a formatted column, for the columns that have one — 'Price' reads '£15.5m' and sorts as 15.5. Sorting the string instead puts £9.0m above £15.5m, and parsing it back means teaching every client each competition's units.
             */
            values: {
                [key: string]: number;
            };
            /**
             * Tone
             * @default neutral
             * @enum {string}
             */
            tone: "neutral" | "good" | "warning";
            /**
             * Ruled Out
             * @description Whether his status means he will not play, rather than that he might not — decided by the provider, which knows its platform's words for it.
             * @default false
             */
            ruled_out: boolean;
        };
        /**
         * PlayerDetail
         * @description Everything worth knowing about one player, on demand.
         *
         *     Fetched when someone asks rather than carried by every row: the interesting
         *     numbers differ per competition and there are a dozen of them, which is a table
         *     nobody can read attached to a payload nobody needs.
         */
        PlayerDetail: {
            /** Player Id */
            player_id: string;
            /** Name */
            name: string;
            /** Position */
            position: string;
            /**
             * Team
             * @description The club as a table spells it: 'DET', 'TOT'.
             */
            team: string;
            /**
             * Team Name
             * @description The same club in full — 'Detroit Lions', 'Tottenham Hotspur'. A drawer has room for the name a person would say, where a column has room for three letters. Empty falls back to `team` rather than leaving the line blank.
             * @default
             */
            team_name: string;
            /**
             * Team Logo Url
             * @description The club's crest on the platform's own CDN, or empty where it has none.
             * @default
             */
            team_logo_url: string;
            /**
             * Headline
             * @description The one figure this player is judged on, bare — '22.3', not '22.3 proj pts'. Empty when there is none, which is not the same as zero.
             * @default
             */
            headline: string;
            /**
             * Headline Label
             * @description What that figure is: 'projected this week', 'xPts this week'. When `headline` is empty this stands alone and says why there is no figure, so it reads as a sentence rather than as a number that failed to arrive.
             * @default
             */
            headline_label: string;
            /**
             * Note
             * @description Injury or availability news, in the platform's words.
             * @default
             */
            note: string;
            /**
             * Url
             * @description This player on the platform's own site, where one exists.
             * @default
             */
            url: string;
            /**
             * Image Url
             * @description Portrait on the platform's own CDN, or empty where that competition has none. A URL rather than bytes: it is the client that has a cache for it.
             * @default
             */
            image_url: string;
            /**
             * Tone
             * @default neutral
             * @enum {string}
             */
            tone: "neutral" | "good" | "warning";
            /** Groups */
            groups: components["schemas"]["StatGroup"][];
            /**
             * Tables
             * @description Comparisons across periods, which a list of groups cannot show.
             */
            tables: components["schemas"]["StatTable"][];
        };
        /**
         * PlayerPage
         * @description One window onto a player list, and how much there is to page through.
         */
        PlayerPage: {
            /** Players */
            players: components["schemas"]["PlayerCard"][];
            /**
             * Total
             * @description Rows matching the filters, before the window.
             * @default 0
             */
            total: number;
            /**
             * Offset
             * @default 0
             */
            offset: number;
            /**
             * Positions
             * @description Every position in the unfiltered pool, so a filter can be offered without guessing.
             */
            positions: string[];
        };
        /**
         * Remedy
         * @description The one thing worth offering for a failure.
         */
        Remedy: {
            /**
             * Action
             * @description What the page offers: start the platform login, open Settings, ask again, or follow `url` off the app.
             * @enum {string}
             */
            action: "authorize" | "settings" | "retry" | "link";
            /**
             * Label
             * @description The control's words: 'Apply for API access'.
             */
            label: string;
            /**
             * Url
             * @description Where a link goes; empty for every other action.
             * @default
             */
            url: string;
            /**
             * Command
             * @description What a terminal does instead, or empty where it has nothing to run.
             * @default
             */
            command: string;
        };
        /** Remembered[ScoutReport] */
        Remembered_ScoutReport_: {
            answer: components["schemas"]["ScoutReport"];
            /**
             * Inputs
             * @description A digest of what the answer was given; a fresh ask compares against it.
             */
            inputs: string;
            /**
             * Answered At
             * Format: date-time
             */
            answered_at: string;
        };
        /** Reply */
        Reply: {
            /** Answer */
            answer: string;
        };
        /**
         * ScheduleRow
         * @description One week of your own season, played or still to come.
         */
        ScheduleRow: {
            /**
             * Label
             * @description What the league calls the week: 'Week 3', 'GW 12'.
             */
            label: string;
            /**
             * Date
             * @description When it is played, in the reader's words: 'Sep 14', 'Sat 13 Sep'.
             * @default
             */
            date: string;
            /**
             * Opponent
             * @description Who you play. Empty on a bye, which is not an opponent named 'bye'.
             * @default
             */
            opponent: string;
            /**
             * Detail
             * @description Their record, or however the league identifies them.
             * @default
             */
            detail: string;
            /**
             * Result
             * @description The score once it is played, and nothing before that.
             * @default
             */
            result: string;
            /**
             * Outcome
             * @description How it ended, once it has; None before.
             */
            outcome: ("won" | "lost" | "drawn") | null;
            /**
             * Is Current
             * @default false
             */
            is_current: boolean;
            /**
             * Playoffs
             * @default false
             */
            playoffs: boolean;
        };
        /**
         * ScoutReport
         * @description A scouting report for any competition: the model's judgement, with the week's own figures and items.
         *
         *     The first four fields are what the model wrote, as `ScoutAnswer` in
         *     `application/formats.py` describes them to it; the engine adds what it
         *     does not get to write, so nothing here asks it to leave a field alone.
         */
        ScoutReport: {
            /** Situation */
            situation: string;
            /** Focus */
            focus: string[];
            /** Moves */
            moves: components["schemas"]["Move"][];
            /** Strategy */
            strategy: string;
            /**
             * Tasks
             * @description The to-do items as computed, each carrying its verdict.
             */
            tasks: components["schemas"]["Action"][];
            /**
             * Headline
             * @description Figures read straight from the platform, never written by the model.
             */
            headline: components["schemas"]["Stat"][];
        };
        /**
         * Setting
         * @description One configurable value, described without ever carrying a secret.
         */
        Setting: {
            /** Key */
            key: string;
            /** Field */
            field: string;
            /** Secret */
            secret: boolean;
            /** Present */
            present: boolean;
            /**
             * Kind
             * @enum {string}
             */
            kind: "text" | "boolean" | "integer" | "number" | "choice";
            /**
             * Choices
             * @default []
             */
            choices: string[];
            /**
             * Value
             * @default
             */
            value: string;
            /**
             * Shadowed
             * @default false
             */
            shadowed: boolean;
            /**
             * Effective
             * @default
             */
            effective: string;
        };
        /** SettingsUpdate */
        SettingsUpdate: {
            /** Values */
            values: {
                [key: string]: string;
            };
        };
        /**
         * Side
         * @description One team in a matchup — yours, or the one you are playing.
         */
        Side: {
            /** Name */
            name: string;
            /**
             * Detail
             * @description Record, manager, or however the league identifies a team.
             * @default
             */
            detail: string;
            /**
             * Points
             * @description What they have scored, or are projected to.
             * @default
             */
            points: string;
            /** Lineup */
            lineup: components["schemas"]["Spot"][];
            /** Bench */
            bench: components["schemas"]["Spot"][];
        };
        /**
         * Spot
         * @description One place in a lineup, or one player on a bench.
         *
         *     Competition-neutral on purpose: a slot is "FLEX" in the NFL and "" in the
         *     Premier League, where a formation has positions but not named places, and
         *     both render the same.
         */
        Spot: {
            /**
             * Player Id
             * @description Identifier this competition uses, for opening the player.
             * @default
             */
            player_id: string;
            /**
             * Slot
             * @description Named place in the lineup, where the competition has them.
             * @default
             */
            slot: string;
            /** Player */
            player: string;
            /**
             * Detail
             * @description Position, club and opponent, as that competition words it.
             */
            detail: string;
            /**
             * Value
             * @description The forward-looking number, with its unit.
             */
            value: string;
            /**
             * Tone
             * @default neutral
             * @enum {string}
             */
            tone: "neutral" | "good" | "warning";
        };
        /**
         * StandingRow
         * @description One team in the league table.
         */
        StandingRow: {
            /** Rank */
            rank: number;
            /** Name */
            name: string;
            /**
             * Detail
             * @description Manager, or however the league identifies the entry.
             * @default
             */
            detail: string;
            /**
             * Record
             * @description In the league's own terms: '3-1', '2W 1D 1L'.
             * @default
             */
            record: string;
            /**
             * Points
             * @description What the table is actually sorted on.
             * @default
             */
            points: string;
            /**
             * Team Id
             * @description Addresses this team's roster. Empty where the platform cannot serve one.
             * @default
             */
            team_id: string;
            /**
             * Playoffs
             * @description Chance of a playoff place, formatted. Empty where the season is not simulated.
             * @default
             */
            playoffs: string;
            /**
             * Is Mine
             * @default false
             */
            is_mine: boolean;
        };
        /**
         * Stat
         * @description One headline figure: where the team stands before any reading happens.
         *
         *     Computed by the provider from league state, never by the model — these are
         *     exact and a hallucinated rank or bank balance would be worse than none.
         */
        Stat: {
            /**
             * Label
             * @description Short name in the league's own vocabulary: 'Bank', 'Free transfers'.
             */
            label: string;
            /**
             * Value
             * @description Already formatted for display, with its unit: '£2.5m', '340,112', '0-0'.
             */
            value: string;
            /**
             * Tone
             * @description Whether this figure should pull the eye. 'warning' for something costing points now — points left on the bench, an expiring allowance — and 'good' for headroom worth spending.
             * @default neutral
             * @enum {string}
             */
            tone: "neutral" | "good" | "warning";
        };
        /**
         * StatGroup
         * @description A handful of related figures under a heading.
         *
         *     Twenty numbers in one list is a wall; the same twenty under "This week",
         *     "Season" and "Set pieces" can be read without looking for anything.
         */
        StatGroup: {
            /** Title */
            title: string;
            /** Stats */
            stats: components["schemas"]["Stat"][];
        };
        /**
         * StatRow
         * @description One line of a table across every column: a measure over the periods, or a game over the measures.
         */
        StatRow: {
            /** Label */
            label: string;
            /**
             * Values
             * @description One per column, in the same order. 'N/A' where that column has no answer — distinct from '0', which is an answer.
             */
            values: string[];
            /**
             * Tone
             * @default neutral
             * @enum {string}
             */
            tone: "neutral" | "good" | "warning";
        };
        /**
         * StatTable
         * @description Figures on a grid, so they can be read across as well as down.
         *
         *     A stack of per-season groups makes you hold last year's goals in your head
         *     while you scroll to this year's. A table puts them on one line, which is
         *     the whole reason anybody looks at more than one season — and a game log is
         *     the same grid turned the other way, a game to a row and a measure to a column.
         */
        StatTable: {
            /** Title */
            title: string;
            /**
             * Columns
             * @description Column headings, the subject first: periods newest first, ['2026/27', '2025/26'], or measures, ['Pts', 'Snaps', 'Car'].
             */
            columns: string[];
            /** Rows */
            rows: components["schemas"]["StatRow"][];
            /**
             * Absent
             * @description What a cell reads where its column has no answer, so a client can tell it from a figure.
             * @default N/A
             */
            absent: string;
        };
        /**
         * Subject
         * @description What a conversation is about: one to-do item, by its key, or one player.
         *
         *     A question is asked of something on screen. Naming the thing is what lets
         *     the conversation be seeded with that thing and not the whole week.
         */
        Subject: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "task" | "player";
            /**
             * Key
             * @description The to-do item's key, or the player's id.
             */
            key: string;
        };
        /**
         * Summary
         * @description Where a team stands, with no analysis in it.
         *
         *     Everything here is read or computed from league state, so it is available
         *     the moment a page opens rather than after a model has answered.
         */
        Summary: {
            /** Headline */
            headline: components["schemas"]["Stat"][];
            mine: components["schemas"]["Side"] | null;
            opponent: components["schemas"]["Side"] | null;
            /** Swaps */
            swaps: components["schemas"]["Swap"][];
            /** Actions */
            actions: components["schemas"]["Action"][] | null;
            /** Fixtures */
            fixtures: components["schemas"]["Stat"][];
            /** @description One-time advantages the manager can spend, and what has become of each — carrying its own title, because the league names them: FPL calls them chips. None in a competition that has no such thing. */
            boosts: components["schemas"]["StatGroup"] | null;
            /**
             * Window
             * @description When this week actually is, already formatted — 'Week 1 · Sep 11-15', 'GW 2 · deadline Sat 22 Aug 10:30'. A week with no dates on it is a number.
             * @default
             */
            window: string;
            forecast: components["schemas"]["Forecast"] | null;
        };
        /**
         * Swap
         * @description A change the numbers already imply, before anyone has judged them.
         */
        Swap: {
            /** Start */
            start: string;
            /**
             * Out
             * @description Who comes out. Empty when a place was unfilled.
             * @default
             */
            out: string;
            /** Gain */
            gain: string;
        };
        /**
         * TaskVerdict
         * @description The model's judgement on one computed to-do item.
         */
        TaskVerdict: {
            /** Task */
            task: string;
            /**
             * Decision
             * @enum {string}
             */
            decision: "AGREE" | "OVERRULE" | "WAIT";
            /** Reason */
            reason: string;
        };
        /**
         * TeamRef
         * @description One team in the league, addressable so its roster can be opened.
         */
        TeamRef: {
            /**
             * Team Id
             * @description Identifier this platform uses for a team, roster or entry.
             */
            team_id: string;
            /** Name */
            name: string;
            /**
             * Detail
             * @description Record, manager, or however the league identifies them.
             * @default
             */
            detail: string;
            /**
             * Url
             * @description This team on its own platform, where there is such a page.
             * @default
             */
            url: string;
            /**
             * Is Mine
             * @default false
             */
            is_mine: boolean;
        };
        /**
         * Thread
         * @description A conversation opened about one thing; asked through the chat endpoint.
         */
        Thread: {
            /** Chat Id */
            chat_id: string;
        };
        /**
         * TradeIdea
         * @description A trade worth offering, priced in what it does to the playoff race.
         */
        TradeIdea: {
            /** Team Id */
            team_id: string;
            /**
             * Team
             * @description The manager to offer it to.
             */
            team: string;
            /** Giving */
            giving: string[];
            /** Receiving */
            receiving: string[];
            /**
             * Playoffs
             * @description Your chance of a playoff place with the trade made.
             */
            playoffs: number;
            /**
             * Playoffs Change
             * @description That chance less your chance without it.
             */
            playoffs_change: number;
            /**
             * Their Playoffs Change
             * @description The same for the other side: what you would hand a rival.
             */
            their_playoffs_change: number;
            /**
             * Points
             * @description Your starters' projected points a week, with the trade less without it.
             */
            points: number;
            /**
             * Their Points
             * @description The same for theirs, which is the case for them saying yes.
             */
            their_points: number;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input: unknown;
            /** Context */
            ctx: Record<string, never>;
        };
        /**
         * WeekAhead
         * @description One coming week for your roster: what its best lineup projects, and what to do if that is short.
         *
         *     Byes and injuries are known weeks out, and a week where several land at
         *     once is a loss that can be seen coming: this is where it is seen, while
         *     there is a waiver run or two to fix it.
         */
        WeekAhead: {
            /** Week */
            week: number;
            /**
             * Points
             * @description Your best legal lineup's projection that week.
             */
            points: number;
            /**
             * Usual
             * @description What your best lineup projects in a typical one of these weeks.
             */
            usual: number;
            /**
             * Missing
             * @description Regular starters who will not play that week, and why: 'Josh Allen (bye)'.
             */
            missing: string[];
            /**
             * Short
             * @description Whether the week falls far enough below the usual to act on.
             */
            short: boolean;
            /**
             * Fix
             * @description The pickup that closes most of the gap, and who to drop for him.
             * @default
             */
            fix: string;
            /**
             * Gain
             * @description What that pickup adds to the week's best lineup.
             * @default 0
             */
            gain: number;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_sports_api_competitions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Competition"][];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    capabilities_api_capabilities_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Capabilities"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    read_settings_api_settings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Setting"][];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    save_settings_api_settings_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SettingsUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Setting"][];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    yahoo_login_state_api_yahoo_login_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginState"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    start_yahoo_login_api_yahoo_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginState"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    list_leagues_api__competition__leagues_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LeagueRef"][];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    roster_api__competition__leagues__league_id__roster_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlayerCard"][];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    player_api__competition__leagues__league_id__players__player_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
                player_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlayerDetail"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    summary_api__competition__leagues__league_id__summary_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Summary"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    decide_api__competition__leagues__league_id__items_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ItemDecision"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ItemState"] | null;
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    free_agents_api__competition__leagues__league_id__free_agents_get: {
        parameters: {
            query?: {
                offset?: number;
                limit?: number;
                /** @description Column to order by. Empty means the competition's own ranking. */
                sort?: string;
                descending?: boolean;
                /** @description Keep only this position. Empty keeps all. */
                position?: string;
                /** @description Substring match across a row's own values. */
                search?: string;
            };
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlayerPage"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    teams_api__competition__leagues__league_id__teams_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TeamRef"][];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    team_roster_api__competition__leagues__league_id__teams__team_id__roster_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
                team_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlayerCard"][];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    schedule_api__competition__leagues__league_id__schedule_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LeagueSchedule"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    weeks_ahead_api__competition__leagues__league_id__weeks_ahead_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WeekAhead"][];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    trades_api__competition__leagues__league_id__trades_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TradeIdea"][];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    scout_api__competition__leagues__league_id__scout_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScoutReport"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    judgment_api__competition__leagues__league_id__judgment_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Remembered_ScoutReport_"] | null;
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    thread_api__competition__leagues__league_id__threads_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Subject"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Thread"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    judge_free_agents_api__competition__leagues__league_id__free_agents_judge_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["JudgeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlayerCall"][];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    free_agent_calls_api__competition__leagues__league_id__free_agents_calls_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                competition: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CallsRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlayerCall"][];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    ask_api_chat__chat_id__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                chat_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChatRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Reply"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
}
