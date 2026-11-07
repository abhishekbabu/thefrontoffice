# The Front Office

[![CI](https://github.com/abhishekbabu/thefrontoffice/actions/workflows/ci.yml/badge.svg)](https://github.com/abhishekbabu/thefrontoffice/actions/workflows/ci.yml)

An AI general manager for your fantasy teams. It reads your live league, real
stats and the fixtures ahead, turns them into a to-do list for the week, and
with a model judges each item and answers questions about any player.

![This week](docs/screenshots/week.png)

| Competition | Platform | Credentials |
|---|---|---|
| NFL | Sleeper | Username |
| Premier League | Fantasy Premier League | Entry id |
| NBA | Yahoo Fantasy | OAuth (one browser login) |

## Features

- **To-do list.** It covers starters who are out or on bye, empty slots, bench
  swaps, next week's byes with no cover, free agents whose role just grew, and
  the trade deadline. Each item names the fix, the player to drop and its
  deadline. Dismiss or snooze any item; a dismissed one returns if it changes.
- **Win chance and playoff odds.** The week is simulated 10,000 times from each
  starter's own games and live scores, and the season 5,000 times. Every move
  shows what it does to both chances.
- **Weeks ahead and trades.** It projects the next four weeks as the roster
  stands, and names the free agent who fixes a short week. It finds one-for-one
  trades that help both sides and ranks them by your playoff chance.
- **Free agents.** Ranked by projection. Columns show the fit against your
  weakest starter, the change in this week's win chance, and growing usage
  ("snaps 34→76%").
- **Player drawer.** Role and matchup, ESPN news, injury designation and a game
  log for every player.
- **Model in place.** A verdict on each to-do item, a call on each free agent,
  and a **Why?** chat under any row or player. Answers are kept, so asking again
  with unchanged input costs nothing. Without a model key, none of it is shown.
- **CLI.** The same competitions in the terminal, including trade evaluation.

Every view has its own URL (`/nfl-sleeper/<league>/team`). NFL has the deepest
analysis; FPL and NBA share the week, team and league pages.

| | | |
|---|---|---|
| ![Leagues](docs/screenshots/landing.png) | ![Free agents](docs/screenshots/free-agents.png) | ![Player](docs/screenshots/player.png) |

## Quick start

Install [uv](https://docs.astral.sh/uv/) (0.13.5 or newer, which fetches
Python 3.15 for you) and [just](https://just.systems):

```bash
brew bundle                                          # macOS / Linux
winget install --id=astral-sh.uv --id=Casey.Just -e   # Windows
```

Then:

```bash
just install                # uv sync + git hooks
cp .env.template .env       # PowerShell: Copy-Item .env.template .env
just ui                     # http://localhost:8000
```

Add credentials in the app's **Settings** page or in `.env`; the page writes
`.env` and applies it without a restart. `just doctor` reports what this machine
can run, and never prints a secret.

- **NFL**: your Sleeper username.
- **Premier League**: the number in your points page URL,
  `fantasy.premierleague.com/entry/<THIS>/event/1`.
- **NBA**: a [Yahoo developer app](https://developer.yahoo.com/apps/), then
  `just yahoo-login` (see [Yahoo access](#yahoo-access)).
- **Analysis (optional)**: a free key from
  [Gemini](https://aistudio.google.com/app/apikey),
  [Groq](https://console.groq.com/keys) or
  [OpenRouter](https://openrouter.ai/settings/keys). With several keys, a call
  goes to the first one that has quota.

`just run` starts the CLI instead: `/week`, `/roster`, `/scout`, `/trade <text>`,
`/leagues`, `/help`.

## Configuration

Every variable is a validated field on `AppSettings` in
[`config/settings.py`](src/thefrontoffice/config/settings.py). A malformed value
fails at startup and names the field.

| Variable | Default | Notes |
|---|---|---|
| `SLEEPER_USERNAME` | — | Enables NFL |
| `FPL_ENTRY_ID` | — | Enables FPL |
| `YAHOO_CLIENT_ID` / `YAHOO_CLIENT_SECRET` | — | Enables NBA |
| `YAHOO_REDIRECT_URI` | `https://localhost:8080` | Must match the Yahoo app's registered URI |
| `YAHOO_MAX_WEEKLY_ADDS` | `3` | The NBA add budget |
| `GOOGLE_API_KEY` | — | Gemini, tried first |
| `GROQ_API_KEY` | — | Groq, tried second |
| `OPENROUTER_API_KEY` | — | OpenRouter, tried third |
| `GROQ_ANALYSIS_MODEL` / `GROQ_PARSING_MODEL` | `openai/gpt-oss-120b` / `openai/gpt-oss-20b` | |
| `OPENROUTER_ANALYSIS_MODEL` / `OPENROUTER_PARSING_MODEL` | `nvidia/nemotron-3.5-super-vl:free` | Any `:free` model with structured outputs |
| `LOGFIRE_TOKEN` | — | Exports traces to [Logfire](https://logfire.pydantic.dev); nothing leaves without it |
| `LOGFIRE_ENVIRONMENT` | `local` | |
| `LOGFIRE_CAPTURE_PROMPTS` | `false` | Exports prompt text, which carries your roster |
| `LOG_LEVEL` | `INFO` | |

The `*_CACHE_DIR`, `ANSWER_CACHE_DIR` and `ITEM_STATE_DIR` variables move the
on-disk caches and kept state.

On a second machine, copy `.env` by hand and run `just yahoo-login` again.
Don't copy `.yahoofantasy`: two machines sharing one refresh token invalidate
each other.

### Yahoo access

```bash
just yahoo-login            # opens a browser; the token is cached in .yahoofantasy
just yahoo-login --force    # discard the token and authorize again
```

The browser warns about the self-signed localhost certificate; that is expected.
If every Fantasy endpoint answers **403**, one of these is missing:

- Yahoo has to [approve the app](https://sports.yahoo.com/developer/access/)
  for Fantasy Sports API access. Personal use is an accepted category.
- **API Permissions → Fantasy Sports → Read** has to be saved *before* you
  authorize. A token keeps the grant it was issued with, so fix the permission
  and then run `just yahoo-login --force`.

## Development

```bash
just check          # lint, format, types, tests, 95% coverage floor
just check-web      # UI: API types in step, lint, typecheck, tests, bundle budget
just api            # FastAPI on :8000, reloading
just web            # Vite on :5173 with hot reload, proxying /api
just shots          # screenshot every view into web/.shots, reporting console errors
just api-types      # regenerate web/src/lib/schema.ts after changing a response model
just backtest       # score the win-chance simulation on finished weeks (live data)
just tune           # search the simulation's range settings (live data)
just --list         # everything else
```

Tests are hermetic: no network, no credentials, no cache on disk. Fakes for the
platforms and the model live in `tests/support/`. Live-API tests are marked
`integration` and deselected by default. CI runs the same `just` recipes on
Linux, macOS and Windows. `just shots` needs Playwright's browser once:
`cd web && pnpm exec playwright install --only-shell chromium`.

Rules for agents and contributors are in [`AGENTS.md`](AGENTS.md); skills are in
[`.agents/skills/`](.agents/skills/).

## Architecture

Ports and adapters, with dependencies pointing inward only. `tests/test_architecture.py`
enforces this.

```text
src/thefrontoffice/
├── domain/          models, ports and errors; imports nothing else in the package
├── application/     use cases over ports: the week, season, wire, trades, answers
├── adapters/
│   ├── inbound/     the CLI, and the FastAPI app that serves the React UI
│   └── outbound/    platform clients, the model, one provider per competition
├── bootstrap.py     the only module naming a concrete class; builds the registry and wiring
└── config/          settings, the .env writer, telemetry
web/                 React 19, Vite, TypeScript, Tailwind v4, Radix
```

- **Competitions.** Each one is a provider under `adapters/outbound/competitions/`
  plus one `CompetitionEntry` in `bootstrap.py`. Its capabilities are read from
  the ports its provider implements. See the
  [`adding-a-competition`](.agents/skills/adding-a-competition/SKILL.md) skill.
- **Platforms.** Sleeper is the NFL league platform and the stats source for both
  NFL and NBA. FPL comes from its public API, NBA leagues from Yahoo through
  `yahoofantasy`, and news and injuries from ESPN. Every client caches to disk
  and retries transient failures. A platform that stays down answers 503 with
  `platform_unavailable`.
- **Model.** One `AnalysisModel` port covers Gemini, Groq and OpenRouter, with
  failover by quota. Answers are Pydantic models, never parsed prose.
  The answer formats live in `application/formats.py`, and each competition's
  prompts in its own `prompt.py`.
- **API.** Routes return the domain models directly. The UI's TypeScript types
  are generated from the OpenAPI schema. Every failure is one `ErrorBody` with a
  code and a remedy. The API sends meaning, such as tones, roles, verdicts and
  sort order, so the UI only renders.
- **Web UI.** Pages are lazy-loaded to keep first paint under 150 kB gzip. Color
  comes only from semantic `light-dark()` tokens, themed by palette and by
  light/dark mode.
- **Tracing.** OpenTelemetry via Logfire, configured only in `config/telemetry.py`.

## Security

`.env`, `.yahoofantasy` and the `.*_cache/` directories are gitignored, and a
pre-commit hook rejects private keys. Settings are read only through the
`settings` singleton, and a secret's value never leaves the process.
