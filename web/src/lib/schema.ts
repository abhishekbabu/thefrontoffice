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
        get: operations["list_sports"];
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
        get: operations["capabilities"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Leagues
         * @description Every league this account plays in for the competition `key` names: 'nba-yahoo', never a bare 'nba'.
         */
        get: operations["list_leagues"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Refresh
         * @description Drop what is kept of one league that a move or a new week changes, so its pages read the platform again.
         *
         *     Each read is kept as long as its answer usually holds — a Yahoo roster an
         *     hour — which is too long right after the manager has made a move.
         */
        post: operations["refresh"];
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
         * @description Every configurable value, grouped by what it unlocks, with secrets reported as present or absent.
         *
         *     A secret's contents never leave the process. There is nothing the UI can
         *     do with the characters of an API key that it cannot do with the fact
         *     that one is set, and a page that renders them puts them in screenshots.
         */
        get: operations["read_settings"];
        /**
         * Save Settings
         * @description Write values to .env and re-read configuration into the running app.
         *
         *     Rejects any key no setting reads rather than writing it: a line nothing
         *     picks up looks saved and changes nothing, which is the exact failure
         *     this endpoint exists to prevent.
         */
        put: operations["save_settings"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platforms/{platform}/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Login State */
        get: operations["login_state"];
        put?: never;
        /**
         * Start Login
         * @description Begin the platform's handshake and return at once.
         *
         *     The browser tab it opens is on this machine — the server and the person
         *     are the same place — but the click cannot be waited on inside a request,
         *     so progress is reported through the companion GET.
         */
        post: operations["start_login"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platforms/{platform}/capture": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Capture Status
         * @description When the platform's browser sync last stored anything, for Settings to say beside the bookmark.
         */
        get: operations["capture_status"];
        put?: never;
        /**
         * Ingest Capture
         * @description Store what the sync bookmark fetched before replying: the hand-over is the only copy.
         */
        post: operations["ingest_capture"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platforms/{platform}/capture/plan": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Capture Plan
         * @description What the sync bookmark should fetch next, for the comma-separated league keys it has found so far.
         *
         *     Called from the platform's own page, so the bookmark knows nothing of
         *     what the app reads: it fetches what this says, hands it back, and asks
         *     again until there is nothing new to fetch.
         */
        get: operations["capture_plan"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/roster": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Roster
         * @description One card per player, with per-competition columns rendered generically, in the order asked.
         *
         *     The columns are the competition's own vocabulary — FPL sends Price and xGI,
         *     football sends Depth — so the client reads whatever keys arrive rather
         *     than being taught each competition. Ordered here, by the rule a page of
         *     the wire is, so a column sorts alike on every table.
         */
        get: operations["roster"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/players/{player_id}": {
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
        get: operations["player"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/players/{player_id}/tabs/{tab}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Player Tab
         * @description One tab of a player's drawer that is read only when opened (`PlayerDetail.deferred`).
         */
        get: operations["player_tab"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/compare": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Compare
         * @description Up to four players side by side, from what each one's drawer shows.
         */
        get: operations["compare"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/players": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Search Players
         * @description Players whose name holds `search`, rostered or not, for a comparison to add.
         */
        get: operations["search_players"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/untouchables": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Untouchables
         * @description The players on your roster you marked untouchable: never a drop, a trade away or a sale.
         *
         *     A mark on a player no longer yours is dropped here, against the roster as it reads now.
         */
        get: operations["untouchables"];
        put?: never;
        /**
         * Mark Untouchable
         * @description Mark one player untouchable, or clear his mark; every untouchable in the league after it.
         */
        post: operations["mark_untouchable"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/week": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Week
         * @description Where the team stands this week, before any report is asked for.
         *
         *     The page would otherwise be blank for as long as a model call takes,
         *     showing nothing the app already knows. To-do items carry what the
         *     manager decided about them — dismissed, snoozed, or back since.
         */
        get: operations["week"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/weeks/{week}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Week Of
         * @description Another week of the season: one played as it finished, one to come as the rosters project.
         *
         *     The week being played is `/week`'s, with its to-do list and its
         *     forecast; this answers the rest, with neither. Offered only where a
         *     competition can, so one that cannot refuses rather than answering
         *     with the week being played.
         */
        get: operations["week_of"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/weeks/{week}/games": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Games Of
         * @description The real games of any week of the season, the week being played included, and its byes.
         */
        get: operations["games_of"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/items": {
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
         * @description Dismiss, snooze or restore one to-do item; what the decision makes of it, for its row to show.
         */
        post: operations["decide"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/free-agents": {
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
        get: operations["free_agents"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/free-agents/calls": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Kept Calls
         * @description The kept call on each free agent on screen, without asking the model anything.
         *
         *     What lets the wire show its calls on load. A player whose situation
         *     has moved since his call comes back marked stale.
         */
        get: operations["kept_calls"];
        put?: never;
        /**
         * Judge Free Agents
         * @description A call on each of the free agents on screen, to show on their rows.
         */
        post: operations["judge_free_agents"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/teams": {
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
        get: operations["teams"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/teams/{team_id}/roster": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Team Roster
         * @description Somebody else's squad, in the same columns as your own, ordered as yours is.
         */
        get: operations["team_roster"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/teams/{team_id}/outlook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Team Outlook
         * @description Somebody else's next few weeks as their roster stands, as `/outlook` reads your own.
         */
        get: operations["team_outlook"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/season": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Season
         * @description The league beyond this week: the season, the table, the real games.
         *
         *     Separate from `/week` because it answers a different question and
         *     costs requests the week does not need — nobody checking their lineup
         *     should wait on the whole season's fixtures.
         */
        get: operations["season"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/outlook": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Outlook
         * @description Your next few weeks as your roster stands, and a pickup for any that comes up short.
         *
         *     Offered only where a competition can project them, as trades are, so
         *     one that cannot refuses rather than answering with no weeks.
         */
        get: operations["outlook"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/trades": {
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
        get: operations["trades"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/judgment": {
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
        get: operations["judgment"];
        put?: never;
        /**
         * Judge
         * @description Judge the week's to-do list — or return the kept judgment where nothing has changed.
         */
        post: operations["judge"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/competitions/{key}/leagues/{league_id}/chats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Open Chat
         * @description Open the conversation that follows you around this league.
         *
         *     Briefed on nothing yet: each question says what is on screen, and is
         *     briefed on whatever of that it has not seen. Its turns are then read and
         *     asked by its id, like any other conversation.
         */
        post: operations["open_chat"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/chats/{chat_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Turns
         * @description What has been said in a conversation so far — what a page reopened on it shows.
         *
         *     An id this process does not hold is `chat_expired`, the client's cue to open another.
         */
        get: operations["turns"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/chats/{chat_id}/turns": {
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
         * @description Ask the next question in an open conversation; every turn so far, the answer last.
         *
         *     The whole conversation rather than the answer alone, so the client shows
         *     what the server holds instead of keeping a copy of its own in step.
         */
        post: operations["ask"];
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
            kind: "lineup" | "waiver" | "trade" | "transfer" | "chip";
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
             * Pickup
             * @description For an add, what he is added for: 'streamer' (this week's games) or 'keeper' (the rest of the season). None for anything else, and where the league does not say.
             */
            pickup: ("streamer" | "keeper") | null;
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
            /**
             * Players
             * @description Who the move brings in and takes out, figure by figure, for a side-by-side reading. Empty where it moves one player or none: `evidence` says what it rests on then.
             */
            players: components["schemas"]["MovePlayer"][];
            /** @description The model's judgement, once a report has been run. None before, and for an item it skipped. */
            verdict: components["schemas"]["TaskVerdict"] | null;
            /**
             * Stale
             * @description Whether the item has changed since `verdict` was given: a verdict on last night's news.
             * @default false
             */
            stale: boolean;
            /** @description What the manager's own decisions make of the item. */
            mark: components["schemas"]["ItemMark"];
            /** @description `win_change` as it reads — '+2.8% to win', toned by its sign. Written where the week is presented, so a page and a terminal say it alike; None where unpriced. */
            chance: components["schemas"]["Stat"] | null;
            /**
             * Fingerprint
             * @description What this item currently says, so a verdict on an older version of it reads as stale.
             *
             *     Everything a judgement rested on and nothing it produced: the move,
             *     the reason, the deadline, the evidence and the figures compared — not the verdict itself.
             */
            readonly fingerprint: string;
        };
        /**
         * ActivityMove
         * @description One player a league move moved: who, and which way, for which team.
         */
        ActivityMove: {
            /**
             * Player Id
             * @description Identifier this platform uses for the player, so his page opens; empty for FAAB a trade moved.
             */
            player_id: string;
            /** Player */
            player: string;
            /**
             * Position
             * @default
             */
            position: string;
            /**
             * Team
             * @description His real-world club.
             * @default
             */
            team: string;
            /**
             * Change
             * @enum {string}
             */
            change: "added" | "dropped";
            /**
             * Manager
             * @description Whose roster gained or lost him: two in a trade.
             * @default
             */
            manager: string;
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
            /**
             * Moves
             * @description Each player it moved, for the move's own page. Empty where unknown.
             */
            moves: components["schemas"]["ActivityMove"][];
            /**
             * Bid
             * @description What a waiver claim was won with, already formatted; empty for none.
             * @default
             */
            bid: string;
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
        /**
         * Capture
         * @description What one round of a browser sync hands over.
         */
        Capture: {
            profile: components["schemas"]["CapturedResponse"];
            /** Responses */
            responses: components["schemas"]["CapturedResponse"][];
        };
        /**
         * CapturePlan
         * @description What a browser should fetch next, given what the app already holds.
         *
         *     Planned again after each hand-over: what one response holds (a league's
         *     current week, its teams) decides what the next round asks for. A browser
         *     stops when a plan asks for nothing it has not already fetched.
         */
        CapturePlan: {
            /**
             * Base
             * @description The URL every step's path is fetched below, with the browser's session.
             */
            base: string;
            /**
             * Probe
             * @description Fetched first: anything but 200 means the browser is not signed in.
             */
            probe: string;
            /** Steps */
            steps: components["schemas"]["CaptureStep"][];
        };
        /**
         * CaptureReceipt
         * @description What one hand-over stored, and what it refused.
         */
        CaptureReceipt: {
            /** Stored */
            stored: number;
            /**
             * Leagues
             * @description Each league that had something stored, by key.
             */
            leagues: string[];
            /**
             * Errors
             * @description Each response refused, with why.
             */
            errors: string[];
        };
        /**
         * CaptureStatus
         * @description How fresh the capture is, for the page that offers the sync.
         */
        CaptureStatus: {
            /**
             * Active
             * @description Whether the app reads this platform from the capture rather than its API.
             */
            active: boolean;
            /** Synced At */
            synced_at: string | null;
            /**
             * Leagues
             * @description The leagues captured this season, by name.
             */
            leagues: string[];
            session: components["schemas"]["SessionStatus"] | null;
        };
        /**
         * CaptureStep
         * @description One response the app wants a browser to fetch.
         */
        CaptureStep: {
            /**
             * Path
             * @description Below the plan's `base`, exactly as fetched and as handed back.
             */
            path: string;
            /**
             * League
             * @description The league it belongs to; empty for one about the account.
             * @default
             */
            league: string;
        };
        /**
         * CapturedResponse
         * @description One response a browser fetched: its body and nothing of the session that fetched it.
         */
        CapturedResponse: {
            /** Path */
            path: string;
            /** Status */
            status: number;
            /** Body */
            body: string;
        };
        /**
         * CategoryLine
         * @description One scoring category of a category league's week: each side's figure, and who leads it.
         */
        CategoryLine: {
            /**
             * Name
             * @description The category as the league abbreviates it: 'PTS', 'FG%'.
             */
            name: string;
            /**
             * Mine
             * @description Your side's figure, as the league prints it; empty before any is recorded.
             */
            mine: string;
            /**
             * Theirs
             * @description The other side's figure, the same way.
             */
            theirs: string;
            /**
             * Lead
             * @description Who is ahead in it, with the category's own direction read in (fewer turnovers wins). None where there is nothing yet to compare.
             */
            lead: ("mine" | "theirs" | "even") | null;
            /**
             * Win
             * @description Your chance of winning the category by the week's end; None where the week is not forecast.
             */
            win: number | null;
        };
        /**
         * ChatRequest
         * @description A question, and what was on screen when it was asked.
         */
        ChatRequest: {
            /** Message */
            message: string;
            /** On Screen */
            on_screen?: components["schemas"]["Subject"][];
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
            /** Week Word */
            week_word: string;
            /** Judges Wire */
            judges_wire: boolean;
            /** Plans Weeks */
            plans_weeks: boolean;
            /** Browses Weeks */
            browses_weeks: boolean;
            /** Finds Trades */
            finds_trades: boolean;
            /** Searches Players */
            searches_players: boolean;
            /** Refreshes */
            refreshes: boolean;
            /** Syncs */
            syncs: boolean;
            /** Configured */
            configured: boolean;
            /** Requires */
            requires: string;
            blocked: components["schemas"]["ErrorBody"] | null;
        };
        /**
         * ErrorBody
         * @description A failure as every inbound adapter reports it: what went wrong, which condition, and what can be done.
         */
        ErrorBody: {
            /** Detail */
            detail: string;
            /**
             * Code
             * @enum {string}
             */
            code: "error" | "platform_unavailable" | "capture_required" | "session_expired" | "unknown_competition" | "not_configured" | "unsupported" | "subject_gone" | "item_decision" | "ai_unavailable" | "ai_key_invalid" | "ai_quota" | "ai_failed" | "login_required" | "access_not_approved" | "chat_expired" | "not_found" | "invalid_request" | "unknown_setting" | "settings_unwritable";
            remedy: components["schemas"]["Remedy"] | null;
        };
        /**
         * FixtureRun
         * @description One player's matches over the weeks ahead, with why the row is worth a look.
         */
        FixtureRun: {
            /** Player Id */
            player_id: string;
            /** Player */
            player: string;
            /**
             * Detail
             * @description Position and club: 'MID · LIV'.
             * @default
             */
            detail: string;
            /**
             * Weeks
             * @description One per week the grid covers, in order, a blank included.
             */
            weeks: components["schemas"]["FixtureWeek"][];
            /**
             * Flags
             * @description What earns the row its place, in words: 'blank GW14', 'double GW15', '3 hard', 'injured'.
             */
            flags: string[];
        };
        /**
         * FixtureWeek
         * @description One week of a player's run: no match is a blank, two a double.
         */
        FixtureWeek: {
            /** Week */
            week: number;
            /** Games */
            games: components["schemas"]["Opposition"][];
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
         * ItemMark
         * @description What the manager's decisions make of one to-do item as it reads now.
         */
        ItemMark: {
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
         * Judgment
         * @description A league's kept judgment of its week, as the week page reads it back.
         */
        Judgment: {
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
            /**
             * Due
             * @description Whether the week has moved on far enough to judge it again unasked: the to-do list holds an item this judgment never saw, or what it was given has changed and it is over twelve hours old. Never while the list is empty — there is nothing left to judge.
             * @default false
             */
            due: boolean;
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
        };
        /**
         * LoginState
         * @description Where a platform's login handshake has got to.
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
            /**
             * Home Score
             * @description Points on the board once it has kicked off.
             */
            home_score: number | null;
            /** Away Score */
            away_score: number | null;
            /**
             * Kickoff
             * @description When it starts, in UTC, for the page to show in the viewer's own zone.
             */
            kickoff: string | null;
            /**
             * Yours
             * @description Your players in this game, starters first. Empty where you have none.
             */
            yours: components["schemas"]["PlayerRef"][];
            /**
             * Theirs
             * @description Your opponent's players in this game, starters first; empty where none.
             */
            theirs: components["schemas"]["PlayerRef"][];
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
         * MovePlayer
         * @description One player a to-do item moves, with the figures it is weighed on.
         *
         *     Every player on an item carries the same rows in the same order, so the
         *     player coming in and the one going out read side by side as data — never
         *     parsed out of a sentence.
         */
        MovePlayer: {
            /**
             * Side
             * @description Whether the move brings him in or takes him out.
             * @enum {string}
             */
            side: "in" | "out";
            /** Player Id */
            player_id: string;
            /** Name */
            name: string;
            /**
             * Position
             * @default
             */
            position: string;
            /**
             * Team
             * @description His real-world club.
             * @default
             */
            team: string;
            /**
             * Held
             * @enum {string}
             */
            held: "starter" | "bench" | "reserve" | "free agent" | "waivers" | "market";
            /**
             * Figures
             * @description The rows he is compared on, labelled alike for every player on the item; '—' where he has none.
             */
            figures: components["schemas"]["Stat"][];
        };
        /**
         * Opposition
         * @description One match a club plays in a week to come, as a fixture grid cell reads it.
         */
        Opposition: {
            /**
             * Opponent
             * @description The club faced, as a table spells it: 'ARS'.
             */
            opponent: string;
            /** Home */
            home: boolean;
            /**
             * Difficulty
             * @description The league's own 1-5 rating of the match for the club facing it; 5 hardest.
             */
            difficulty: number;
        };
        /**
         * Outlook
         * @description The next few weeks for your roster, soonest first, each measured against the same usual week.
         */
        Outlook: {
            /**
             * Usual
             * @description What your best lineup projects in a typical one of these weeks. None once none are left.
             */
            usual: number | null;
            /**
             * Measure
             * @description What a week's `points` count: projected points, or the games the daily lineups can start where a week is won on how many games are played.
             * @default proj
             * @enum {string}
             */
            measure: "proj" | "games";
            /** Weeks */
            weeks: components["schemas"]["WeekAhead"][];
            /**
             * Run Weeks
             * @description The weeks a fixture grid covers, soonest first — where the competition projects its weeks ahead as fixtures rather than as lineups. Empty otherwise.
             */
            run_weeks: number[];
            /**
             * Runs
             * @description The players whose run has something to act on — a blank, a double, a hard stretch, a doubt.
             */
            runs: components["schemas"]["FixtureRun"][];
            /**
             * Clear
             * @description Players on the roster whose run has nothing to flag, left off `runs`.
             * @default 0
             */
            clear: number;
            /**
             * Warnings
             * @description Each week a blank or a double lands on the roster, naming who: 'GW14' — '3 blank: Saka, Rice, Raya'.
             */
            warnings: components["schemas"]["Stat"][];
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
         *     he will play.
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
             * Ruled Out
             * @description Whether his status means he will not play, rather than that he might not — decided by the provider, which knows its platform's words for it.
             * @default false
             */
            ruled_out: boolean;
            /**
             * Notes
             * @description A cell's fuller reading, by column, where the cell abbreviates it — 'Bowers Q' reads 'Without Brock Bowers (TE, Q): 6.10/game in 3 games · 8.60 with'. Shown as its tooltip.
             */
            notes: {
                [key: string]: string;
            };
            /**
             * Tones
             * @description A cell's tone, by column, where it has one other than neutral — an Opponent cell good against a soft defense. The cell's text says the same, for anyone who cannot see the color.
             */
            tones: {
                [key: string]: "neutral" | "good" | "warning";
            };
            /**
             * Roles
             * @description The columns a table renders as more than text, by what they hold — so no client matches names.
             */
            readonly roles: {
                [key: string]: "player" | "status" | "slot";
            };
        };
        /**
         * PlayerComparison
         * @description Players side by side: who each is, and the figures they share on one grid.
         */
        PlayerComparison: {
            /**
             * Players
             * @description Each player's header, in the order asked: name, club, the one figure, owner. No groups or tables.
             */
            players: components["schemas"]["PlayerDetail"][];
            /**
             * Tables
             * @description One per heading the measures came under — 'Week 11', 'Projected line', '2026 season' — each a row per measure and a column per player, in the order of `players`.
             */
            tables: components["schemas"]["StatTable"][];
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
             * @description Injury or availability news, in words — 'Out', 'Questionable', FPL's own sentence — never a platform's bare code, which alone in a header reads as a figure ('O' as zero).
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
            /**
             * Rank
             * @description Where he ranks at his position this season: 'WR12'. Empty before he has played.
             * @default
             */
            rank: string;
            /**
             * Owner
             * @description Whose roster he is on in this league — a team's name, or 'Free agent'. Empty where the league has no such thing, as in FPL, where any number of managers can hold one player.
             * @default
             */
            owner: string;
            /**
             * Tabs
             * @description The drawer's tabs in the order shown, by the names its groups and tables carry. Empty is one page of everything, in the order sent.
             */
            tabs: string[];
            /** Groups */
            groups: components["schemas"]["StatGroup"][];
            /**
             * Tables
             * @description Comparisons across periods, which a list of groups cannot show.
             */
            tables: components["schemas"]["StatTable"][];
            /**
             * Moves
             * @description Each league move he was part of, oldest first, as the league's activity shows it.
             */
            moves: components["schemas"]["ActivityRow"][];
            /**
             * Moves Tab
             * @description Which tab his moves sit in, by name; empty for the first.
             * @default
             */
            moves_tab: string;
            /**
             * Deferred
             * @description Tabs whose sections are read only when opened, each from the player's tab route: they cost a request the rest of the drawer does not. Offered whether or not they turn out to hold anything.
             */
            deferred: string[];
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
             * Limit
             * @description The window's size, which the next page steps by.
             * @default 50
             */
            limit: number;
            /**
             * Positions
             * @description Every position in the unfiltered pool, so a filter can be offered without guessing.
             */
            positions: string[];
            /**
             * Views
             * @description Other lists of the pool the competition offers, by name: 'Trending', 'IR'. Empty where none.
             */
            views: string[];
            /**
             * Hints
             * @description What a column measures, by its heading, where the heading alone would mislead: said on hover.
             */
            hints: {
                [key: string]: string;
            };
        };
        /**
         * PlayerRef
         * @description A player found by name, enough to tell him from another and to open him.
         */
        PlayerRef: {
            /** Player Id */
            player_id: string;
            /** Name */
            name: string;
            /**
             * Detail
             * @description Position, club and owner: 'WR · DAL · Rival'.
             * @default
             */
            detail: string;
        };
        /**
         * Refreshed
         * @description What a refresh dropped.
         */
        Refreshed: {
            /**
             * Dropped
             * @description How many kept platform reads went, to be asked for again on the next page.
             */
            dropped: number;
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
             * Platform
             * @description Whose login an authorize starts: 'yahoo'; empty otherwise.
             * @default
             */
            platform: string;
            /**
             * Command
             * @description What a terminal does instead, or empty where it has nothing to run.
             * @default
             */
            command: string;
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
             * @description The score once it is played, the score so far while it is, and nothing before that.
             * @default
             */
            result: string;
            /**
             * Outcome
             * @description How it ended, once it has; None before, and while it is being played.
             */
            outcome: ("won" | "lost" | "drawn") | null;
            /**
             * Is Current
             * @default false
             */
            is_current: boolean;
            /**
             * Marks
             * @description What else falls in the week, in the league's words: 'Trade deadline'. Empty for most.
             */
            marks: string[];
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
         * SessionStatus
         * @description How the server's last read of a platform with the person's session cookie went.
         */
        SessionStatus: {
            /** Fetched At */
            fetched_at: string | null;
            /**
             * Expired
             * @description Whether the platform refused the cookie now set.
             * @default false
             */
            expired: boolean;
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
            /**
             * Mode
             * @default
             */
            mode: string;
            /**
             * Hint
             * @default
             */
            hint: string;
        };
        /**
         * SettingsGroup
         * @description The settings that unlock one thing, and what to know before setting them.
         */
        SettingsGroup: {
            /** Title */
            title: string;
            /** Note */
            note: string;
            /**
             * Section
             * @enum {string}
             */
            section: "platforms" | "ai" | "advanced";
            /**
             * Platform
             * @default
             */
            platform: string;
            /**
             * Switch
             * @default
             */
            switch: string;
            /**
             * Modes
             * @default {}
             */
            modes: {
                [key: string]: string;
            };
            /** Settings */
            settings: components["schemas"]["Setting"][];
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
             * Record
             * @description Their season record now, in the league's own terms: '7-4', '6W 1D 4L'. Empty where the league keeps none — a classic FPL table — or would not say.
             * @default
             */
            record: string;
            /**
             * Detail
             * @description Anything else the league identifies a team by: 'GW12 picks'.
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
            /**
             * Open Spots
             * @description Roster spots the team holds nobody in, outside its reserve: room to add a player without dropping one. 0 where the roster is full or the league does not say.
             * @default 0
             */
            open_spots: number;
            /**
             * Reserve
             * @description Players held in a slot that costs no roster spot and cannot start, such as injured reserve or taxi, in rows shaped like the bench's. Empty where the league has none.
             */
            reserve: components["schemas"]["Spot"][];
        };
        /**
         * Slate
         * @description The real games one fantasy week is made of, and the clubs with none in it.
         */
        Slate: {
            /**
             * Games
             * @description In kickoff order.
             */
            games: components["schemas"]["Match"][];
            /**
             * Byes
             * @description Clubs with no game that week, alphabetical; empty where every club plays, or none has played yet.
             */
            byes: string[];
            /**
             * Note
             * @description One line on the slate as a whole, where it is not to be read as complete; empty for most.
             * @default
             */
            note: string;
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
             * Mark
             * @description A role the row carries beyond its place, as the league abbreviates it — FPL's captain 'C' and vice-captain 'VC'. Shown as a chip beside the name; empty for most rows.
             * @default
             */
            mark: string;
            /**
             * Detail
             * @description Position, club and opponent, as that competition words it.
             */
            detail: string;
            /**
             * Value
             * @description The number the row turns on, with its unit: a projection, or once his game has kicked off, what he has scored.
             */
            value: string;
            /**
             * Tone
             * @default neutral
             * @enum {string}
             */
            tone: "neutral" | "good" | "warning";
            /**
             * Today
             * @description Whether he plays in the scoring period under way, where a lineup is set day by day: 'vs TOR today', '@ BOS live', 'no game today'. Empty where the competition sets lineups by the week, or it is unknown.
             * @default
             */
            today: string;
            /**
             * Idle
             * @description He has no game today (`today`): a start there scores nothing until he is swapped out.
             * @default false
             */
            idle: boolean;
            /**
             * Kickoff
             * @description When his game starts, in UTC, while it has not: the page shows it in the viewer's own zone, as the hour beside `today` where a lineup is set by the day. None once it has kicked off, and where the time is unknown.
             */
            kickoff: string | null;
            /**
             * Scoring
             * @description Which kind of number `value` is: projected before his game, live while it is on, final after. None where the competition does not say.
             */
            scoring: ("projected" | "live" | "final") | null;
            /**
             * Scored
             * @description What he has scored, bare — empty until his game kicks off. Shown beside `projection`.
             * @default
             */
            scored: string;
            /**
             * Projection
             * @description What he is projected, shown beside what he has scored on every row that says how it scores — the guess beside the answer, and before kickoff the only number there is.
             * @default
             */
            projection: string;
            /**
             * Line
             * @description His figures in each category the league scores, in its order, where a row shows them as columns — a category week played, or his game today once it tips off. Labelled alike on every row of the side; empty for most.
             */
            line: components["schemas"]["Stat"][];
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
             * Points Against
             * @description Points scored against, formatted; empty where none.
             * @default
             */
            points_against: string;
            /**
             * Waiver Budget
             * @description Waiver budget left, formatted: '$73'. Empty where none.
             * @default
             */
            waiver_budget: string;
            /**
             * Waiver Order
             * @description Place in the waiver order: '3'. Empty where none.
             * @default
             */
            waiver_order: string;
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
            /**
             * Url
             * @description Where the figure comes from, to open: the article a headline is from. Empty for most.
             * @default
             */
            url: string;
            /**
             * Better
             * @description Which way this figure improves; null where it does not compare, like an opponent or a college.
             */
            better: ("higher" | "lower") | null;
            /**
             * Hint
             * @description What the label means, where it is the app's own measure rather than the league's: a tooltip.
             * @default
             */
            hint: string;
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
            /**
             * Note
             * @description What the heading says about the group as a whole: '2 available'.
             * @default
             */
            note: string;
            /**
             * Tab
             * @description Which of a player drawer's tabs it sits in, by the tab's name; empty for the first.
             * @default
             */
            tab: string;
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
            /**
             * Better
             * @description Which way this measure improves; null where it does not.
             */
            better: ("higher" | "lower") | null;
            /**
             * Best
             * @description The cells holding the best figure, by index — set only on a comparison, and only where at least two figures compare and they differ.
             */
            best: number[];
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
             * Tab
             * @description Which of a player drawer's tabs it sits in, by the tab's name; empty for the first.
             * @default
             */
            tab: string;
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
         * @description Something on screen a question is asked with: one to-do item, by its key, one player, or one page.
         *
         *     Naming the thing is what lets the conversation be briefed on that thing
         *     and not the whole league.
         */
        Subject: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "task" | "player" | "page";
            /**
             * Key
             * @description The to-do item's key, the player's id, or one of ('matchup', 'schedule', 'fixtures', 'team', 'trades', 'free-agents', 'league').
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
            /**
             * Categories
             * @description A category league's head-to-head, one line per category, in the league's order. Empty in a points league, and in a week with no opponent.
             */
            categories: components["schemas"]["CategoryLine"][];
            /** @description Where this week sits in the season, for paging to another. None in a competition that shows only the week being played. */
            weeks: components["schemas"]["WeekRange"] | null;
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
         * @description A conversation opened on the server; asked through its turns.
         */
        Thread: {
            /** Chat Id */
            chat_id: string;
        };
        /**
         * TradeIdea
         * @description A trade worth offering, priced in what it does to the playoff race and to the playoffs themselves.
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
             * Giving Ids
             * @description Who you give, by player id, in the order of `giving`: to open them.
             */
            giving_ids: string[];
            /**
             * Receiving Ids
             * @description Who you get, by player id, in the order of `receiving`.
             */
            receiving_ids: string[];
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
             * @description Your starters' projected points a week over the regular season left, with the trade less without it — or, where `Trades.measure` is categories, the categories you expect to win a week.
             */
            points: number;
            /**
             * Their Points
             * @description The same for theirs over every week left, which is the case for them saying yes.
             */
            their_points: number;
            /**
             * Playoff Points
             * @description Your starters' projected points a playoff week, with the trade less without it.
             */
            playoff_points: number | null;
            /**
             * Total
             * @description Your starters' expected points over the rest of the season, with the trade less without it: every regular-season week left, and each playoff week weighed by your chance of being in it.
             */
            total: number;
            /**
             * Their Playoffs
             * @description Their chance of a playoff place before the trade: out of it, they have only worth to weigh.
             * @default 0
             */
            their_playoffs: number;
            /**
             * Pickup
             * @description The free agent added to the roster spot a two-for-one frees, where not the list's shared one.
             * @default
             */
            pickup: string;
            /**
             * Form
             * @description The players in it whose own games move their price off their projection, and why, each said on the first trade he is in.
             */
            form: components["schemas"]["Stat"][];
        };
        /**
         * Trades
         * @description The trades worth offering, best first, with what most of them share said once rather than on each.
         */
        Trades: {
            /** Ideas */
            ideas: components["schemas"]["TradeIdea"][];
            /**
             * Measure
             * @description What each idea's figures for a lineup count: fantasy points, or expected categories won.
             * @default points
             * @enum {string}
             */
            measure: "points" | "categories";
            /**
             * Deadline
             * @description The last day the league takes a trade, where known.
             */
            deadline: string | null;
            /**
             * Ranked By
             * @description The figure on each idea the list is ordered by: your playoff chance, or once that is safe, your starters' expected points over the rest of the season.
             * @default playoffs_change
             * @enum {string}
             */
            ranked_by: "playoffs_change" | "total";
            /**
             * Pickup
             * @description The free agent most of the two-for-ones would add to the spot they free; an idea names its own pickup only where it is someone else.
             * @default
             */
            pickup: string;
        };
        /**
         * Turn
         * @description One thing said: by the person, or by the model.
         */
        Turn: {
            /**
             * Role
             * @enum {string}
             */
            role: "you" | "model";
            /** Text */
            text: string;
        };
        /**
         * UntouchableMark
         * @description Marking one player untouchable, or clearing the mark, as the page sends it.
         */
        UntouchableMark: {
            /** Player Id */
            player_id: string;
            /** Untouchable */
            untouchable: boolean;
        };
        /**
         * Untouchables
         * @description The players on your roster you will not let go, in one league, by id.
         *
         *     The manager's own judgement, which no figure here can overrule: none of
         *     them is ever named as a drop, given away in a trade idea, or sold.
         */
        Untouchables: {
            /** Player Ids */
            player_ids: string[];
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
             * Missing
             * @description Regular starters who will not play that week, and why: 'Josh Allen (bye)'.
             */
            missing: string[];
            /**
             * Short By
             * @description How far the week falls below the usual one; negative where it is above.
             */
            short_by: number;
            /**
             * Short
             * @description Whether the week falls far enough below the usual to act on.
             */
            short: boolean;
            /**
             * Light
             * @description Regulars with few games that week, where a week counts games: 'Jalen Brunson (2 games)'.
             */
            light: string[];
            /**
             * Heavy
             * @description Whether most clubs play four or more games that week: a stream brings more of them.
             * @default false
             */
            heavy: boolean;
            /**
             * Provisional
             * @description Whether the league has days of that week still to schedule, so its games are a floor.
             * @default false
             */
            provisional: boolean;
            /**
             * Fix
             * @description The pickup that closes most of the gap, and who to drop for him.
             * @default
             */
            fix: string;
            /**
             * Gain
             * @description What that pickup adds to the week, in its competition's measure.
             * @default 0
             */
            gain: number;
        };
        /**
         * WeekRange
         * @description Which week a page shows, the week being played, and how far either way the season can be browsed.
         */
        WeekRange: {
            /** Week */
            week: number;
            /** Current */
            current: number;
            /** First */
            first: number;
            /** Last */
            last: number;
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
    list_sports: {
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    capabilities: {
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    list_leagues: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    refresh: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
                    "application/json": components["schemas"]["Refreshed"];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    read_settings: {
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
                    "application/json": components["schemas"]["SettingsGroup"][];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    save_settings: {
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
                    "application/json": components["schemas"]["SettingsGroup"][];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    login_state: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                platform: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    start_login: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                platform: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    capture_status: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                platform: string;
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
                    "application/json": components["schemas"]["CaptureStatus"];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    ingest_capture: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                platform: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Capture"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CaptureReceipt"];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    capture_plan: {
        parameters: {
            query?: {
                leagues?: string;
            };
            header?: never;
            path: {
                platform: string;
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
                    "application/json": components["schemas"]["CapturePlan"];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    roster: {
        parameters: {
            query?: {
                /** @description Column to order by. Empty means the competition's own ranking. */
                sort?: string;
                descending?: boolean;
            };
            header?: never;
            path: {
                key: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    player: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    player_tab: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
                league_id: string;
                player_id: string;
                tab: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    compare: {
        parameters: {
            query: {
                ids: string[];
            };
            header?: never;
            path: {
                key: string;
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
                    "application/json": components["schemas"]["PlayerComparison"];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    search_players: {
        parameters: {
            query?: {
                search?: string;
            };
            header?: never;
            path: {
                key: string;
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
                    "application/json": components["schemas"]["PlayerRef"][];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    untouchables: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
                    "application/json": components["schemas"]["Untouchables"];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    mark_untouchable: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
                league_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UntouchableMark"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Untouchables"];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    week: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    week_of: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
                league_id: string;
                week: number;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    games_of: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
                league_id: string;
                week: number;
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
                    "application/json": components["schemas"]["Slate"];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    decide: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
                    "application/json": components["schemas"]["ItemMark"];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    free_agents: {
        parameters: {
            query?: {
                /** @description Column to order by. Empty means the competition's own ranking. */
                sort?: string;
                descending?: boolean;
                offset?: number;
                limit?: number;
                /** @description Keep only this position. Empty keeps all. */
                position?: string;
                /** @description Substring match across a row's own values. */
                search?: string;
                /** @description One of the page's `views` to list instead of the whole pool. Empty is the pool. */
                view?: string;
            };
            header?: never;
            path: {
                key: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    kept_calls: {
        parameters: {
            query: {
                ids: string[];
            };
            header?: never;
            path: {
                key: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    judge_free_agents: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    teams: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    team_roster: {
        parameters: {
            query?: {
                /** @description Column to order by. Empty means the competition's own ranking. */
                sort?: string;
                descending?: boolean;
            };
            header?: never;
            path: {
                key: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    team_outlook: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
                    "application/json": components["schemas"]["Outlook"];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    season: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    outlook: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
                    "application/json": components["schemas"]["Outlook"];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    trades: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
                    "application/json": components["schemas"]["Trades"];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    judgment: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
                    "application/json": components["schemas"]["Judgment"] | null;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    judge: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    open_chat: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key: string;
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    turns: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                chat_id: string;
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
                    "application/json": components["schemas"]["Turn"][];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
    ask: {
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
                    "application/json": components["schemas"]["Turn"][];
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
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Bad Gateway */
            502: {
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
}
