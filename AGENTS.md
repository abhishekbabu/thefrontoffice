# The Front Office — Agent Rules

Project overview, setup, architecture and commands live in [`README.md`](README.md).
This file is only the rules an agent needs that the README does not already state.

Skills live in [`.agents/skills/`](.agents/skills/); see [`.agents/AGENTS.md`](.agents/AGENTS.md)
for the index.

## Before committing

`just check` (lint, format, types, tests, 95% coverage floor) must pass. The
pre-commit hooks run the same gates, so a commit that skips them will fail anyway.

Update `README.md` in the same commit when behavior, commands, dependencies or
environment variables change. Prose documentation lives there and in this file;
do not add new doc files.

## Hard rules

**Errors.** Services never signal failure by return value — no `None`, no `[]`,
no `"❌ ..."` string, none of which a caller can tell from a real result. Raise a
`FrontOfficeError` subclass — a platform's from its own `platforms/<p>/errors.py`,
never the domain's; an empty list is an *answer*, a failed request is not. No `print` or `sys.exit` outside
`adapters/inbound/` — exiting takes down a request and leaves nothing to render.
Only inbound adapters render errors. `raise ... from e`, and log before raising
through a module-level `logger = logging.getLogger(__name__)`.

**Dates and times.** Never naive `datetime.now()` or `date.today()` for anything
persisted or compared — store aware UTC, convert at the comparison. Basketball
anchors to `PACIFIC`, because the league schedules by Pacific and a local clock
shifts the day boundary. Parse platform timestamps via `platforms/timestamps.parse_utc`,
which reads a naive one as UTC and converts the rest to it. Keep a date label
(`ScheduledGame.date`, for window tests) distinct from an instant: Sleeper
publishes no tip-off time, so whether a game has happened is settled by its date
against today, and only a game today reads its `status`.

**Naming.** `<Platform>Client` for API clients, `<Platform><Competition>Provider` for
providers, `<Verb>Engine` for use cases, `<What>Error` for domain errors.
Competition-specific constants lead with it: `NBA_SCOUT_PROMPT`,
`MOCK_NFL_REPORT`. The word for a set of players a manager owns is **roster**,
everywhere. Test modules mirror the module they cover.

Under `adapters/outbound/competitions/<competition>/`, the provider file is named for the
platform that owns the **league** — `nba/yahoo.py`, `nfl/sleeper.py`. Other
platforms a competition reads from are role-named helpers (`projections.py`,
`lineup.py`), never a second file named after a platform. A provider that
outgrows one file splits the same way each time — `week.py` (state), `views.py` (how a player reads),
`league.py` (season, table), `prompt.py` (model text), `rules.py` (shared facts) — leaving the port behind.

**Types.** Avoid `Any`; prefer builtin generics and PEP 604 unions, which ruff's
`UP` rules enforce. yahoofantasy is read as `Any` (`replace-imports-with-any`):
it sets attributes via `setattr` at runtime. There is no `type: ignore` anywhere —
fix the type, the fake or the port instead, and disable no check globally.

**Yahoo.** Responses go through our own `JsonDiskCache`, not the SDK's store:
`make_request` is the only fetch that parallelises safely and the vendor's
`_load` takes no expiry. `_load_or_fetch` survives for the scoreboard alone,
where `Week.sync` reads the SDK's store internally and a short `persist_ttl` is
the only way to force a refresh. Cache writes stay on one thread. It raises requests' own exceptions, which escape as a 500 unless passed
through `yahoo.translate`. Never trigger OAuth implicitly — non-interactive
callers use `ensure_authorized`.

**Chat history is resent every turn.** Seed follow-ups with a briefing, not the
generation prompt, and say what was left out.

**Player identity across platforms.** Yahoo and Sleeper share no identifier, so
basketball joins by normalized name — twice, in `competitions/nba/projections.py` and
`competitions/nba/form.py`. Never guess: an ambiguous surname must resolve to nothing
rather than to whichever player was indexed first, and an unmatched player
carries no line rather than borrowing someone else's.

**AI calls.** A strong model analyses, a fast one parses: Gemini 2.5 Pro/Flash,
or each Groq/OpenRouter provider's configured pair. Never a `-preview` model.
Answers are Pydantic models — schema-enforced where the model can, otherwise
validated with one repair — never prose to be regex'd. Gemini's schema cannot
be combined with Search, hence the trade path's second structuring pass.

**Dependencies.** Anything imported directly gets declared directly, never
relied on transitively. Bound both ends (`>=X.Y.Z,<NEXT_MAJOR`), then `just lock`.
System CLIs go in the `Brewfile`. Use `just install` / `just lock` (`uv sync`) —
`uv pip install` ignores `uv.lock`.

**Portability.** Never hardcode `.venv/bin/...` or `.venv/Scripts/...`; `uv run`
resolves it everywhere. No POSIX-only commands in tooling and no `strftime`
dash-modifiers (`%-d`) — both are glibc-only and the project supports Windows.
Format dates through `competitions/dates.py`; put scripts in `scripts/`.

**Secrets.** Never commit `.env`, `.yahoofantasy`, or any `.*_cache/`. Read
config through the `settings` singleton, never `os.getenv` at a call site.
`config/env_file.py` is the only writer: it accepts only keys `AppSettings`
declares, and edits line by line so comments survive. A secret's value must never
leave the process — report presence, never contents. `reload_settings` mutates
the singleton in place; rebinding strands every module that imported it.

**UI.** The API returns the domain models themselves — never a parallel response
type for something `domain/models.py` already models. Provider access lives in
`data.py`, free of any web framework, so it is testable with no server running.
The model is optional: without `GOOGLE_API_KEY` nothing needing one is offered,
rather than offered and refused. Never ship a canned report in the package.

`panels/` holds one page each; `components/ui/` all reused across them — a
second caller moves a component there, never a file shared with whatever else
had no home. Reach for it before writing a card, table, loading state or
control: those drifted per panel, and waiting should look the same everywhere.
Controls are `IconButton`, whose one required `label` is both tooltip and
accessible name. Motion lives in `lib/motion.ts`, via `LazyMotion` from its own
module, or the library lands in the entry bundle.

In `web/`, color comes only from semantic tokens (`bg-card`,
`text-muted-foreground`) — never a raw Tailwind palette utility, which cannot
follow a palette change. Every token is one `light-dark(light, dark)` pair, so a
palette is a `themes.css` block plus a `registry.ts` entry and no component
change. Status colors and the difficulty ramp are deliberately shared across
palettes: they encode meaning, are tuned for color-blind legibility, and clear
WCAG AA against their own ground. State carried in color must also be carried
in text or shape.

**Extract on the second instance.** This app is deliberately shaped so competitions
and platforms differ only where they genuinely differ; everything else is
shared. When you find yourself writing something a second time, extract it then
— not on the third. Existing seams:

- `adapters/outbound/platforms/` — infrastructure every platform needs:
  `http.py` (cached, retried JSON GETs), `retry.py` (transient-failure policy),
  `cache.py` (the disk cache — a directory, one atomically-replaced file per
  key; expiry is a `Freshness` — `within(ttl)`, or what a duration cannot say).
- `adapters/outbound/competitions/` — policy every competition needs: `names.py`
  (cross-platform player matching), `trades.py` (resolving a proposal).
- `domain/` — rules that hold regardless of competition or platform.

**Prefer composition to a base class.** The outbound clients share behaviors,
not a shape: three go through different vendor SDKs and cache differently, while
Sleeper and FPL are both plain public JSON and share `JsonApiClient` — held as a
collaborator, given its own retry policy and domain error, not inherited.

**Telemetry.** All of it lives in `config/telemetry.py`, called once per process
by each entry point. Never open a span by hand or import `logfire` elsewhere: the
libraries carrying the latency are auto-instrumented, which keeps tracing out of
`domain/`, `application/` and the ports. It stays inert without a token
(`send_to_logfire="if-token-present"`), so the suite and CI need no secret. Prompt
text is exported only under `LOGFIRE_CAPTURE_PROMPTS` — a prompt carries the
user's roster and leagues. Each `instrument_*` needs its matching dependency
extra, or it imports fine and raises at call time.

**Headline figures.** `ScoutReport.headline` is filled by the engine from the
provider's `CompetitionContext`, never by the model, which is told to leave it empty
and overwritten regardless — a hallucinated rank sits in the header looking
exactly as authoritative as a real one.

**Layering.** Dependencies point inward only: `domain` imports nothing else in
the package; `application` imports only `domain`; adapters implement ports;
`bootstrap.py` is the one module allowed to name a concrete implementation.
Never import an adapter from `domain/` or `application/` — if an engine needs a
capability, add a port and let `bootstrap` wire it. Engines and providers take their
collaborators — clients, settings — as required arguments; `tests/test_architecture.py` holds all of this.

**Competitions and platforms.** The registry is keyed by the pair, not the
competition: the same one runs on more than one platform, with separate credentials and
separate leagues. Address entries by `entry.key` everywhere outside the
registry; `find` accepts a bare competition only while one platform carries it.

**Adding a competition.** See the `adding-a-competition` skill: a provider under
`adapters/outbound/competitions/`, a prompt template, one `CompetitionEntry` in
`bootstrap.py`. Never name a provider in an entry point, nor put competition specifics
in `domain/`, `application/` or the inbound adapters. If a competition needs a field
the shared models lack, widen them — in the league's own vocabulary, `gains`
rather than `categories_gained`.

## Testing

Mirror the source layout. The default suite must stay hermetic: no network, no
credentials, no cache on disk. Engines and providers take their collaborators
by keyword — use the fakes in `tests/conftest.py` rather than monkeypatching. Providers type each client as
its `…Source` protocol, so a fake is checked against it: fix a drifted fake, never `type: ignore` it. Anything hitting
a live API gets `@pytest.mark.integration`, which is deselected by default.

New code needs tests in the same commit. Coverage is gated at 95%.

## CI

CI runs the same `just` recipes you run locally on Linux, macOS and Windows, so
adding a gate to the `justfile` extends CI too. The UI is a separate `web` job —
`just check-web` locally, `--frozen-lockfile` there. Python 3.15 is required everywhere
— `.python-version`, `requires-python`, pyrefly, ruff, CI — and `[tool.uv] required-version` keeps uv new enough to fetch it.

## Agent documentation

`AGENTS.md` is the source of truth. `CLAUDE.md` beside it is a **symlink** —
never edit it, and never replace it with a real file; two real files drift and
each tool reads a different one. Skills live in `.agents/skills/<name>/SKILL.md`
with `name` and `description` frontmatter, discovered by Claude through the
`.claude/skills` symlink and by Antigravity through `.agent/rules/rules.md`.

Keep every `AGENTS.md` under 200 lines. `just check-agents` enforces all of it.

## Git

Feature branches (`feat/`, `fix/`, `chore/`, `test/`), conventional commit
subjects, and a PR into `main` — the `no-commit-to-branch` hook blocks direct
commits. Delete branches after merging.
