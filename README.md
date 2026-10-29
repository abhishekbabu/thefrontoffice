# The Front Office

[![CI](https://github.com/abhishekbabu/thefrontoffice/actions/workflows/ci.yml/badge.svg)](https://github.com/abhishekbabu/thefrontoffice/actions/workflows/ci.yml)

An AI general manager for your fantasy teams. It reads your live league state,
real stats and the fixtures ahead, then turns it into a to-do list for the
week — and, with a model, judges each item in place and answers questions
about any row or player where it sits.

Three competitions, each on the platform that runs it:

| Competition | Platform | Credentials |
|---|---|---|
| NBA | Yahoo Fantasy | OAuth (one browser login) |
| NFL | Sleeper | Username only |
| Premier League | Fantasy Premier League | Entry id only |

![This week](docs/screenshots/week.png)

## Quick start

**1. Install the two CLIs.** Python is not installed separately — `uv` provisions
the one `requires-python` asks for, Python 3.15. That needs uv 0.13.5 or newer
(`brew upgrade uv`, or `uv self update`); an older one cannot find 3.15.0 and
refuses to run here, saying so.

```bash
brew bundle                                            # macOS / Linux
winget install --id=astral-sh.uv --id=Casey.Just -e     # Windows
```

**2. Install the project.**

```bash
just install                 # uv sync + git hooks
cp .env.template .env        # PowerShell: Copy-Item .env.template .env
```

**3. Add credentials.** Either edit `.env`, or start the app and use its
**Settings** page, which writes `.env` for you and re-reads it into the running
process — no restart. Secrets there are write-only: the server reports whether
one is set, never what it is.

- **NFL** — your Sleeper username.
- **Premier League** — your entry id, the number in the URL of your own points
  page: `fantasy.premierleague.com/entry/<THIS>/event/1`.
- **NBA** — a [Yahoo developer app](https://developer.yahoo.com/apps/) with
  Fantasy Sports **Read** permission and redirect URI `https://localhost:8080`,
  then `just yahoo-login` (see [Yahoo access](#yahoo-access)).
- **Analysis** — a key from any of [Gemini](https://aistudio.google.com/app/apikey),
  [Groq](https://console.groq.com/keys) or [OpenRouter](https://openrouter.ai/settings/keys),
  all free to start. Optional; without one the app offers no analysis rather
  than offering and refusing it. With several, they back each other up: a call
  goes to the first that has quota, in that order.

**4. Run it.**

```bash
just ui     # build the UI and serve it at http://localhost:8000
just run    # interactive CLI instead
```

`just doctor` reports what this machine is configured for, without echoing a
secret, and flags `.env` keys nothing will read.

![League picker](docs/screenshots/landing.png)

## What it does

The app opens on a league picker and every view has its own address, so a page
can be linked, bookmarked or reloaded and Back means what it says.

| Path | Page |
|---|---|
| `/` | every league you can play |
| `/{competition}-{platform}/{league}` | this week, the default view |
| `/{competition}-{platform}/{league}/{view}` | `league`, `team`, `free-agents` |
| `/settings` | credentials and appearance |

A competition with no league (`/nfl-sleeper`) resolves to your first one, and a
path naming a competition you cannot play returns to `/`.

**This week** — your matchup: both lineups side by side, the fixtures behind
them, and the swaps the projections already imply. All read or computed from
league state, so it is complete before a model is asked anything.

On NFL it opens with a **To do** list, most urgent first: a starter ruled out
or on bye, an empty slot, a swap the bench allows, next week's byes with nobody
behind them, the trade deadline, and up to two free agents whose **role just
grew** — a jump in his share of snaps or targets, or in carries, against the
three games before it, while his projection is still at least five points (one
that has fallen back to nothing has usually lost the role again). One big game
is not a role: the jump must hold for his last two games, or come in the latest
week played with a cause — a regular at his position on his team missed that
game and is ruled out of the next. A pickup on a full roster names who to **drop**: the bench player
worth least by his average a game this season — not this week's projection,
which reads a starter on bye as nothing — never one another item moves, one
whose game has kicked off, or one whose role is growing. A breakout only makes
the list when it already beats that player; filling a hole names the drop
whatever it costs. Three or more starters in one real game is an item too: one
bad afternoon there takes them all down together, so it names the best bench
start from another game for the weakest of them, and the forecast's win chance
beside it says whether spreading the risk helps — usually when you are ahead,
rarely when you are behind. Each names the fix — the bench player who
covers, or the best free agent who can play when nobody does — and its deadline
where Sleeper publishes one: a game's day, never a guessed kickoff or waiver time.

Every player a move involves carries what his projection rests on, computed
from Sleeper's per-game stat lines for the weeks already finished: his
**matchup** — how many points a game this week's opponent has given up to his
position, ranked against every defense — and his **role** over his last three
games: snap share, carries, targets and share of the team's targets. The
player drawer shows the same under *Role and matchup*, and the model reads it
on every player line, told to weigh it over the projection and hardest before
a drop. Beside it sits each player's **latest news** from the last ten days, from
his own club's ESPN feed — matched on ESPN's tag or his full name, never a
surname, and never across clubs — in the row, the drawer and the prompt.
The drawer also carries his **game log**: a row per week so far, as Sleeper's
own page reads it — opponent, points in the league's scoring, snap share and the
box score his position is scored on — with byes and games he sat out shown as
gaps, not skipped.

A free agent who **simply outscores one of your starters** — most often a
defense or kicker to stream — is a pickup on the list too: at least three
points over the starter in your best lineup once the bench has moved, and
more than that starter's average a game, so a star's one bad matchup is not a
reason to let him go. At a defense or a kicker the starter he replaces is the
drop, since nobody keeps a spare; elsewhere the drop is chosen as for any
pickup. Two at most; the free-agent page ranks the rest.

**Injury designations** come from ESPN's injury report where it names a player,
joined the same way, and from Sleeper where it does not. Sleeper keeps a
designation until somebody changes it, so the Tuesday after a game a player
ruled out of it still reads Out; ESPN's report is dated and moves with the
week's practices. A player ruled out counts nought toward the lineup, its
total and the best lineup, whatever Sleeper still projects him. A plain Out is
for that week's game alone, so the weeks ahead count only a long ruling — IR,
PUP, a suspension. A free agent's win chance is priced against the lineup your
bench would already make, so he is never credited with filling a slot a bench
player fills anyway.

With a model configured, the list has a **Judge** control: the model judges
each to-do item by its id — *agree*, *overrule* or *wait for news* — and the
verdict appears inside the row it is about, while moves the list missed join it
as *suggested* rows. Nothing runs on load. The latest judgment of each league
is kept (see *Kept answers* below), so a reload shows it, and judging an
unchanged week again returns it without a call. Each item has a stable key — the
hole it fills or the swap it makes — and a fingerprint of what it says; a
verdict on an item that has since changed stays, faded and marked *stale*. The
list itself is the application's: the model cannot add, drop or restate an
item, and a verdict naming no listed item is discarded.

**Win chance.** The NFL week is also simulated 10,000 times: each starter's
outcome drawn from his own games rescaled to this week's projection (thin
histories borrow from his position, whose spread includes last season's games
so the opening weeks have one, and a share of uncertainty in the projection
itself widens every range — the part of it a quarterback shares with his own
receivers drawn once for the whole passing game, so a stack rises and falls
together), whether he plays from his designation,
and finished or live games held at what they have scored — a game under way
adding only what its clock has left, read off ESPN's scoreboard, since
Sleeper's schedule carries no clock and is cached for hours. The same
scoreboard decides which games have kicked off, and a player in one shows his
points so far and where it is ("12:14 - 3rd"). The header carries
the chance of winning with its likely margin; every to-do move carries what it
does to that chance — computed on the same draws, so the difference is the
decision rather than noise — and a move projections would not make but the
simulation rates by a point or more gets a row of its own. A questionable
starter's chance of a zero is why "+2.5 proj pts" can still cost you. The
engine (`application/forecasting.py`) is generic: a competition supplies its
players' ranges through the `ForecastProvider` port. `just backtest` rebuilds
every finished week's matchups as they stood before kickoff and scores the
chances against who won. `just tune` searches the few settings that shape a
range (`RangeSettings` in `nfl/outcomes.py`) on individual player-games — a
season holds thousands, where matchups are too few to tune on — holding the
last week out, and recommends a change only if it is meaningfully better on
that week too.

**Playoff odds.** The rest of the regular season is simulated 5,000 times too
(`application/season.py`, fed through the `SeasonProvider` port): every
remaining fixture is played with each team scoring around the best lineup its
roster projects that week — so byes are seen coming — less what the weeks its
starters miss without warning cost it, rescaled to what the league actually
scores, with the league's own week-to-week spread, and a
per-team offset for how far real strength may sit from projected strength. A
missed week is priced by the league's own rate — how often a regular (half his
team's snaps or more) has sat out a game his team played, 12% by default until
two hundred such games are on record — and costs what the lineup scores with
the bench covering for him, which is what makes a backup worth anything. The
table is seeded by record, then points for. The week's header carries your
chance and what this week is worth to it — "90% · 96% with a win, 83% without"
— weighing this week by the week's own forecast; the league view's header
carries your chance alone, and its table every team's.

**Weeks ahead.** My team opens on the next four weeks as the roster stands
(`nfl/outlook.py`), each one's best legal lineup projected from Sleeper's own
projections for that week — so byes land where they fall — against the
roster's usual week, with the regular starters it will be without and why. An
injury ruling counts as far as it reaches: a plain *Out* covers next week, a
long one (injured reserve, PUP, suspension) every week, and past that the
projection Sleeper keeps publishing stands. A week ten points or more short
names the free agent at a missing player's position who adds most to it, where
he adds at least two points, and, on a full roster, who to drop: never a
regular, anyone a lineup in those weeks leans on, or anyone only away for the week. When next week is the short one it is also a to-do
item, standing in for that week's bye items. Players in reserve slots are not counted on, and are
marked as such on the week's bench.

**Trades worth offering.** Until the deadline, My team tries every
one-for-one swap with every team (`nfl/market.py`) and keeps those that raise
both starting lineups' projected points for the weeks after this one — at least
half a point a week for them, which is the case for their saying yes — and
whose player is worth at least four-fifths of the one they give, each priced by
his projected points over the best free agent at his position, since a manager
weighs what he gets as well as who starts. Kickers
and defenses are left out, being streamed, as are injured-reserve and taxi
players. The twelve best for you are played out against the season over the
same simulated seasons as the league without them, and ranked by what they do
to your playoff chance, which counts what the trade hands the other side: help
a team you are racing and the trade can cost more than it gains.

Every item can be **dismissed** — hidden while it reads as it did, and back,
marked *back — changed since you dismissed it*, the moment its reason, evidence
or deadline changes — or **snoozed** for three hours, until tomorrow at 8am, or
three days. Hidden items wait under a closed *Hidden* at the foot of the list,
each with a way back. Neither needs a model: the list clears itself when league
state settles an item, and these are for the decisions it cannot see — not to
act, or not yet. Decisions are kept per league on this machine
(`ITEM_STATE_DIR`), keyed by the same item key verdicts use.

Questions are asked of the thing they are about. **Why?** under any to-do item
opens a conversation inline, seeded with that item alone — the move, its reason
and evidence, any earlier verdict, the roster and the week's situation — and
asks why, and what would change the call. The player drawer ends with **Ask
about** that player, seeded with everything the drawer shows. Both are smaller
than the report's whole-week context, so cheaper on every resent turn, and both
go through the same failover as everything else. An item settled since the
page loaded is said to be gone rather than answered about.

![Free agents](docs/screenshots/free-agents.png)

**Free agents** — everyone available, ranked by projection, searchable and
filterable by position. On NFL a **Fits** column compares each with the weakest
starter he could replace — "+3.2 over Bernard", or "−0.4 vs Cleveland Browns" in
a deep league where nobody on the wire outprojects a starter — and sorts the
whole pool by it, so the closest replacements come first. Beside it, **Win**
is what starting him would do to this week's chance of winning, at his best
legal start — priced by the same simulation as the to-do list, so a boom-or-bust
receiver can rate above a steadier, higher projection when you are the
underdog. It is priced for the page on screen; sorting by it orders that page.
**Usage** names any growing role — "snaps 34→76%", "carries 1→15" — and sorts
the whole pool by the size of the jump: the pickups a projection has not yet
caught up with. The same rise is on the player's evidence line wherever it is
read.
With a model, **Judge**
puts the first ten rows on screen to it: each gets a call — *add* (and who to
drop), *watch* or *pass* — on a line under its row, grounded in the role,
matchup and news its prompt line carries. Calls are kept per player, so a
reload shows them, judging the page again asks only about the players whose
situation moved, and a call on one who has moved since shows as *stale*.
Each page answers one question. **This week** is what to do before kickoff and
how the game is going: the lineup (and what the bench holds), the opponent, the
score, the chance of winning, what the week is worth to the playoffs, and the
to-do list. **My team** is the roster beyond this week: the weeks ahead, the
trades worth offering (NFL), and the squad in lineup order. **League** is the
season and everyone else in it: your record, place, points and playoff chance;
your results, with the playoff bracket set apart; the table (with each team's
playoff chance, on NFL); every roster; the fixture list; and the transaction
feed. Any player row opens the player.

The other competitions keep the same split. On FPL, the gameweek's header is
the deadline, the eleven's expected points (with the best eleven's, when the
bench holds more), the bank and the free transfers; season points, overall rank
and the mini-league place head League; and **Watch out for** names a club with
a blank or a double gameweek, which no player row can say. On NBA, the week's
header is the add budget left, and League is headed by your record and place.

![Player detail](docs/screenshots/player.png)

The model has no page of its own. It annotates the pages that exist — verdicts
in to-do rows, calls under free-agent rows, a conversation under a row or at
the foot of a player — and none of it appears without a model key: controls
that cannot work are hidden rather than disabled. The old Report and Trade
pages are gone; a trade is still evaluated from the CLI.

**Kept answers.** Every model answer goes through one layer
(`application/answers.py`, behind an `AnswerStore` port, on disk under
`ANSWER_CACHE_DIR` for a week). Each is kept under a scope naming what it is
about — a league's week, or one free agent — with a digest of exactly what the
model was given. Asking again with unchanged input returns the kept answer
without a call; reading never asks; and a caller compares the digest with what
it would send now to mark an answer stale. Anything model-backed added later
asks through the same two calls.

The same three competitions run in the CLI:

| Command | Description |
|---|---|
| `/leagues` | Every league you are in, per competition |
| `/week [competition]` | This week as the page has it: the figures, the chance of winning, the to-do list |
| `/roster [competition]` | Your squad |
| `/scout [competition]` | Analyze a week. No competition runs every configured one |
| `/trade [competition] <text>` | Evaluate a trade. FPL is excluded — its managers transfer against the market rather than trading each other |
| `/help` · `/quit` | — |

![Fantasy Premier League](docs/screenshots/fpl-week.png)

## Configuration

Every variable is a validated field on `AppSettings` in
[`config/settings.py`](src/thefrontoffice/config/settings.py); a malformed value
fails at startup naming the field, not mid-report.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `SLEEPER_USERNAME` | for NFL | — | Sleeper needs no key or OAuth |
| `FPL_ENTRY_ID` | for FPL | — | FPL has no username lookup |
| `YAHOO_CLIENT_ID` | for NBA | — | From your Yahoo developer app |
| `YAHOO_CLIENT_SECRET` | for NBA | — | From your Yahoo developer app |
| `YAHOO_REDIRECT_URI` | no | `https://localhost:8080` | Must match the app's registered URI |
| `YAHOO_MAX_WEEKLY_ADDS` | no | `3` | Integer ≥ 0; the scout's add budget |
| `GOOGLE_API_KEY` | no | — | Gemini. Omit every model key and the app offers no analysis |
| `GROQ_API_KEY` | no | — | Groq, tried after Gemini — and instead of it while Gemini is out of quota |
| `OPENROUTER_API_KEY` | no | — | OpenRouter, tried after Groq |
| `GROQ_ANALYSIS_MODEL` / `GROQ_PARSING_MODEL` | no | `openai/gpt-oss-120b` / `openai/gpt-oss-20b` | Free catalogs change; these are settings for that reason |
| `OPENROUTER_ANALYSIS_MODEL` / `OPENROUTER_PARSING_MODEL` | no | `nvidia/nemotron-3.5-super-vl:free` | Pick any `:free` model; one supporting structured outputs is best |
| `LOGFIRE_TOKEN` | no | — | Write token from a [Logfire](https://logfire.pydantic.dev) project. Omit and nothing is exported |
| `LOGFIRE_ENVIRONMENT` | no | `local` | Separates traces from a laptop and a deployed run |
| `LOGFIRE_CAPTURE_PROMPTS` | no | `false` | Sends prompt and completion **text**. Off deliberately — a prompt carries your roster and leagues |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` |

`YAHOO_CACHE_DIR`, `SLEEPER_CACHE_DIR`, `FPL_CACHE_DIR` and `ESPN_CACHE_DIR`
relocate the per-platform response caches; the defaults are `.yahoo_cache`,
`.sleeper_cache`, `.fpl_cache` and `.espn_cache`.

**On a second machine**, copy `.env` across by hand — the four secrets belong in
a password manager, not in this public repo — then run `just doctor`. Do not
copy `.yahoofantasy`: refresh-token rotation means two machines sharing one
token invalidate each other, and re-authorizing is a single browser flow. The
caches are derived and expiring; leave them behind too.

## Yahoo access

```bash
just yahoo-login    # opens a browser; token cached in .yahoofantasy and reused
```

It is a separate step because the handshake blocks on a browser click, which a
request handler cannot do — so every non-interactive path reports a missing
token rather than trying to obtain one. The browser will warn about the
self-signed localhost certificate; that is expected, and Yahoo only accepts an
`https` redirect.

Two things beyond the login are easy to miss, and both fail the same way — every
Fantasy endpoint answers **403**, including ones needing no user permission,
which is how this is told apart from an invalid token (401):

- **Yahoo reviews every application** before granting Fantasy Sports API access.
  Apply at [sports.yahoo.com/developer/access](https://sports.yahoo.com/developer/access/);
  personal single-league use is an accepted category.
- **API Permissions → Fantasy Sports → Read must be saved** *before* you
  authorize. Yahoo fixes a token's grant at that moment, and a refresh cannot
  widen it, so the fix is `just yahoo-login --force`. The login verifies itself
  rather than reporting success on an inert token.

## Architecture

Ports and adapters, dependencies pointing strictly inward:

```text
src/thefrontoffice/
├── domain/            models and ports. Imports nothing else in the package.
├── application/       use cases over ports: WeekEngine (the week, season and
│                      wire, with forecast, odds and decisions), ScoutEngine…
├── adapters/
│   ├── inbound/       drivers: the CLI and the FastAPI + React web app.
│   └── outbound/      driven: platform clients, the model, and the
│                      per-competition CompetitionProvider implementations.
├── bootstrap.py       composition root: the only module naming a concrete
│                      implementation. Registers competitions, wires engines.
└── config/            validated settings, prompt templates, telemetry.
```

No adapter is named in `domain/` or `application/`; the engines take an
`AnalysisModel` port rather than a vendor client, and the domain's errors name
no platform — each platform's live in its own `platforms/<p>/errors.py`.
Providers are handed their clients by `bootstrap.py`, never build them. A
competition's rules read its own model (`nfl/model.py`: a projection, a team,
the league's rules, a real game), which the league platform's types already
fit; only the provider file names that platform, so the NFL on a second
platform would be one more provider. The
engines answer in figures; `adapters/inbound/presenting.py` puts the generic
ones into words for the web page and the terminal alike, and a competition's own
vocabulary stays its provider's.
`tests/test_architecture.py` checks the import direction and both of these. Adding a competition is a
provider, a prompt template and one `CompetitionEntry` — see the
[`adding-a-competition`](.agents/skills/adding-a-competition/SKILL.md) skill.

**API** — FastAPI returns the domain models directly: `ScoutReport` *is* a
route's response schema, so there is no second representation to keep in step.
It also serves the built UI from `web/dist`, so one process on one port covers
both.

**Platforms** — Yahoo via `yahoofantasy` (OAuth2, rosters, matchups, free agents
sorted by stat category); Sleeper, public and auth-free, which is also the stats
provider for both football and basketball (projections, box scores, schedules,
transactions); Fantasy Premier League, public and auth-free, whose one
`bootstrap-static` call carries the squad, prices, the game's own `ep_next`
projection and Opta expected goals; ESPN, public and auth-free, for the news no
fantasy platform publishes — each NFL club's own feed, and the league's injury
report — joined to Sleeper's players by name within the club. Each caches responses in its own directory.

**Model** — one `AnalysisModel` port, three providers: Gemini via
`google-genai` (`gemini-2.5-pro` for analysis, `gemini-2.5-flash` for parsing),
and Groq and OpenRouter through one OpenAI-compatible adapter on the `openai`
SDK, each with a configured analysis and parsing model. Answers come back as
Pydantic models, never prose to be parsed out: Gemini enforces the schema
itself; for the others the adapter asks in the strongest form the model accepts
(JSON schema, then JSON mode with the schema in the prompt), validates, and
repairs once with the validation errors before failing.

The configured providers sit behind one `RoutedModel` that fails over between
them. A spent quota — a 429, or the 413 Groq returns for a request too large for
the free tier — rests that provider for its `Retry-After` (a minute if it gives
none) and the call moves on; a rejected key or a failed answer moves on without
resting, so a key fixed in Settings counts at once. Cooldowns are shared across
requests. A follow-up chat keeps its own transcript, so it can carry on with
another provider mid-conversation. Only when every provider fails does the call
fail, with the most actionable reason: a key to fix before a quota to wait out.
Groq and OpenRouter calls are traced only under `LOGFIRE_CAPTURE_PROMPTS`,
because that instrumentation records message text regardless.

**Web UI** (`web/`) — React 19, Vite 8, TypeScript 6, Tailwind v4, Radix
primitives, pnpm 12. Each page and Motion are loaded lazily, to hold everything
the first paint loads — the entry and every chunk it preloads — under 150 kB
gzip. Shared pieces live in
`components/ui/`; `panels/` holds one page each. A model's answer is read as
the Markdown subset the models write — paragraphs, headings, lists, bold —
by `lib/prose.ts`, never as HTML. Color is themed in two
orthogonal dimensions — a palette (`data-theme`) and light/dark
(`color-scheme`) — so every token is a single `light-dark(light, dark)`
declaration and no component branches on either.

**Tracing** — OpenTelemetry via `logfire`, configured in
[`config/telemetry.py`](src/thefrontoffice/config/telemetry.py) and nowhere
else. The libraries carrying the latency are auto-instrumented, so no span is
opened by hand and `domain/` and `application/` never learn telemetry exists.
Without `LOGFIRE_TOKEN` nothing is exported and no network call is made.

## Development

```bash
just doctor             # what this machine is configured for
just backtest           # score the win-chance simulation on finished weeks (live data)
just tune               # search the range settings, holding out the last week (live data)
just check              # lint + format + types + tests + 95% coverage floor
just check-web          # lint + typecheck + tests + bundle budget (UI)
just fmt                # auto-fix lint findings, then format
just test               # hermetic suite (args pass through: just test "-k scout")
just lock               # re-resolve uv.lock after editing pyproject.toml
just clean              # caches and build artefacts
just clean-data         # only the platform caches, forcing a refetch
```

`just --list` for the full catalog.

Python is checked by **ruff** (lint and format) and **pyrefly** (types); the UI
by **ESLint** with the React hooks rules and **tsc**. Two of ruff's rule sets
hold rules this repo would otherwise only state: `DTZ` refuses a naive
datetime, and `T20` refuses `print` outside `adapters/inbound/` and `scripts/`.

For UI work, run the two halves separately so the front end hot-reloads:

```bash
just api    # FastAPI on :8000, reloading on change
just web    # Vite on :5173, proxying /api to the above
```

To look at the finished thing:

```bash
just preview   # the real app on its own port, so `just ui` keeps :8000
just shots     # screenshot every view into web/.shots (starts its own preview)
```

Both run the same routes against the same platforms as `just ui` — real data is
where the awkward cases are. `shots` drives it with Playwright and reports any
console errors, which a screenshot of a blank panel otherwise hides. It needs
Playwright's browser once per machine (about 95 MB):
`cd web && pnpm exec playwright install --only-shell chromium`.

When Sleeper, ESPN or FPL itself is down — a 5xx, a timeout, no connection —
the API answers 503 with code `platform_unavailable` and a message saying it is
on that platform's side, and the page offers **Try again**; any other failed
request stays a 400 naming what went wrong.

Tests are hermetic: no network, no credentials, no cache on disk. Engines take
their collaborators by keyword, so the fakes in `tests/support/` stand in for
the platforms and the model; fixtures live in `conftest.py` files, the root's
for every test and a directory's own for its tests alone. Anything hitting a live API is marked
`@pytest.mark.integration` and deselected by default. New code needs tests in
the same commit; coverage is gated at 95%.

CI runs these same `just` recipes on Linux, macOS and Windows, on the Python
version `.python-version` pins plus one newer leg, with `uv sync --locked` and
`pnpm install --frozen-lockfile`. If `just check` and `just check-web` pass
locally they pass in CI.

Agent-facing rules are in [`AGENTS.md`](AGENTS.md), with shared skills under
[`.agents/skills/`](.agents/skills/). `CLAUDE.md` beside any `AGENTS.md` is a
symlink to it, and `.claude/skills` and `.agent/rules/rules.md` are symlinks
too — one source of truth per tool. `just check-agents` enforces that.

## Security

Never commit `.env`, `.yahoofantasy`, or any `.*_cache/` — all are gitignored,
and `detect-private-key` runs as a pre-commit hook. Credentials are read only
through the `settings` singleton, never `os.getenv` at a call site, and a
secret's value never leaves the process.
