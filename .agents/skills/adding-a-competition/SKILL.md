---
name: adding-a-competition
description: Add a new competition or fantasy platform to The Front Office. Use when wiring up a new league provider (the Premier League, ESPN, a second NBA platform), when a competition needs a capability the shared models lack, or when deciding where competition-specific logic belongs.
---

# Adding a Competition

This codebase exists to make this a small change. A competition is a provider
plus a prompt — no entry point, renderer or UI should learn its name.

A **competition** is what a fantasy game is played over: the NBA, the NFL, the
Premier League. A **sport** is basketball, football or soccer, and one sport can
have several competitions, so the sport is an attribute rather than an identity.
A **platform** is where the fantasy leagues live. The registry is keyed by
competition and platform, because either alone collides: one competition runs on
several platforms, and one platform hosts several competitions of a sport.

## The five pieces

1. **Provider** — `adapters/outbound/competitions/<competition>/<platform>.py`, implementing
   `CompetitionProvider` from `domain/ports.py`. The filename is the platform that
   owns the **league**, not every platform the competition reads from: NBA leagues
   live on Yahoo, so the provider is `nba/yahoo.py` even though it also reads
   Sleeper for both stats and projections. Naming it this way leaves room for
   the same competition on a second platform — `nba/sleeper.py` beside
   `nba/yahoo.py`.
   - `sport` / `competition` / `label` class attributes
   - `list_leagues() -> list[LeagueRef]`
   - `build_context(league_id) -> CompetitionContext`
   - `roster_rows(league_id) -> list[dict[str, str]]` — cheap; no projections or
     candidate pool
2. **Prompt template** in `config/constants.py`, rendered by `build_context`.
   Name it `<SPORT>_<REPORT>_PROMPT`.
3. **Registration** — one `CompetitionEntry` in `bootstrap.py`, whose `build`
   constructs the platform clients and hands them in: a provider never builds
   its own. Its capability flags (`supports_trades`, `judges_wire`,
   `plans_ahead`) must match the ports the provider implements, which
   `tests/test_bootstrap.py` checks.
4. **Tests** — a fake platform client, and assertions on the *prompt content*:
   this is where the league rules actually live.

## Where other platforms go

A competition usually reads from more than one platform. Only the league platform
names a file; everything else is a role-named helper beside the provider:

```text
competitions/nba/yahoo.py        provider — Yahoo owns the league
competitions/nba/projections.py  projected totals, read from Sleeper
competitions/nba/form.py         recent form, read from Sleeper
competitions/nba/context.py      prompt lines, built from both
competitions/nfl/sleeper.py      provider — Sleeper owns the league
competitions/nfl/lineup.py       optimal lineup, computed from projections
```

Name helpers for what they produce, not where the data came from. A file called
`sleeper.py` under two different competitions would mean two different things.

## Where the provider's own work goes

A provider answers four separable questions, and past a few hundred lines they
stop fitting in one file. Football and FPL are both split the same way, and a
third competition should reach for the same names before inventing others:

```text
competitions/<competition>/<platform>.py  the port, delegating — leagues, identity, lookups
competitions/<competition>/week.py        the state every view of a week is derived from
competitions/<competition>/league.py      the season, the table, the fixtures, the activity
competitions/<competition>/prompt.py      gathered state rendered as the text a model reads
```

`week.py` is the base: nothing in it imports the others, so `league.py` and
`prompt.py` can both build on it without a cycle. Nothing in `prompt.py`
decides anything — the provider fetches and the prompt describes.

Split when a provider outgrows one file, not on the way in. Basketball is one
file on purpose: a category league has no weekly lineup to solve and almost
none of its methods are free functions, so the same split there would be four
files holding one idea.

Test modules mirror whatever the source ends up as — `nfl/week.py` is tested in
`tests/adapters/outbound/competitions/nfl/test_week.py` — with the fakes they share
in `tests/support/<competition>.py`.

## Rules

**Never name a provider in an entry point.** The CLI, the web UI and the help
text all read `bootstrap.py`. If you are editing `adapters/inbound/` to add a
competition, the design has been bypassed.

**`is_configured` must be honest.** It gates whether a platform is contacted at
all. Building a provider may open an OAuth flow, and a user who does not play
that competition must never be made to sit through one. Check for the credentials the
provider actually needs, and nothing else.

**Widen the shared models; do not fork them.** `Move`, `ScoutReport` and
`TradeVerdict` are deliberately competition-neutral. If a competition needs a field they
lack, add it there and name it in the league's own vocabulary — `gains`, not
`categories_gained`. A second report type means a second renderer and a second
UI path.

**Compute what is computable.** Anything with an exact answer — an optimal
lineup, projected category totals, a transfer budget — belongs in code, handed
to the model as a fact to endorse or overrule. The model's job is judgement:
whether a projection is trustworthy, whether a matchup is bad, whether an injury
designation is real. See `adapters/outbound/competitions/nfl/lineup.py`.

**Degrade, do not fail.** Enrichment that goes missing (trending players,
projections out of season, a matchup that has not started) should reduce the
prompt and say so, not raise. Reserve exceptions for things that make the answer
wrong: no team in the league, an unresolvable player in a trade.

## What each platform already taught us

**FPL.** The only platform that is also its own stats provider: one
`bootstrap-static` call carries prices, `ep_next` and expected goals, so it joins
no names and needs no second source. Money stays in tenths of a million until
displayed — transfer affordability is exact arithmetic. `my-team/{id}` is the one
authenticated endpoint and is deliberately unused; everything in it derives from
the public history (`free_transfers`). Head-to-head leagues live in their own
list, so read both. No trade path: managers transfer against the market.

**Sleeper.** Public and keyless, and used by two competitions. Out of season it
publishes no fixtures at all, so a warning that fires on every player is about
the calendar rather than the team — only flag a missing game when others have one.

**Yahoo.** Reviews each application before granting Fantasy API access, and an
unapproved one gets a valid token every endpoint refuses. Never trigger its
OAuth flow implicitly; it blocks on a browser click.

## Joining players across platforms

Fantasy platforms and stats providers rarely share identifiers. When joining by
name (`adapters/outbound/competitions/nba/projections.py` is the worked example):

- Normalize accents, punctuation and generational suffixes. A hyphen separates
  words (`Karl-Anthony` → `karl anthony`); an apostrophe does not (`De'Aaron` →
  `deaaron`).
- Refuse ambiguity. Two players sharing a surname must resolve to *neither*, not
  to whichever was indexed first.
- An unmatched player carries no data rather than borrowing someone else's.
- Measure the match rate against live data before trusting it.

## Reuse before you write

Check these before implementing anything a competition "needs":

| Need | Use |
|------|-----|
| Match a player name across platforms | `competitions/names.py` — `NameIndex`, `normalize_name` |
| Resolve the players in a trade | `competitions/trades.py` — `resolve_sides` |
| Retry a flaky platform call | `platforms/retry.py` — `build_retry`, `is_transient` |
| Cache a platform response | `platforms/cache.py` — `JsonDiskCache` |
| Talk to a public JSON API | `platforms/http.py` — `JsonApiClient` |

If a second competition needs something the first already does, extract it into one of
those modules rather than copying it. Extract on the second instance, not the
third.

## Trades

Trade support is separate: implement `TradeProvider.build_trade_context` and set
`supports_trades=True` on the `CompetitionEntry`. The engine, the prompt structure and
the verdict model are already shared.

## Checklist

- [ ] `just check` passes (lint, types, tests, 95% coverage floor)
- [ ] No adapter named in `domain/`, `application/` or `adapters/inbound/`
- [ ] Prompt assertions cover the league rules, not just that a string exists
- [ ] Out-of-season and unconfigured paths both tested
