# Audit Playbook

What to look for, per category. Each subagent (or direct pass) gets the relevant
section plus the **Finding format** at the bottom.

A finding is only a finding with evidence. "Probably caches something wrong" is
not a finding; `sleeper/client.py:142 stores a failed response under the success
key` is.

Before reporting anything, check it against `AGENTS.md`. A great many things
that look wrong here are decisions with reasons written down — the vendored
`_load_or_fetch` kept for the scoreboard alone, `missing-attribute` disabled
only for modules touching the yahoofantasy SDK, status colors deliberately
shared across palettes. Those are settled. **A stale rule is itself a finding**:
if the code has drifted from what `AGENTS.md` says, report the drift — one of
the two is wrong and both matter.

---

## 1. Correctness

The highest-trust category — real bugs found by reading, not speculation.

- **Failure signalled by return value.** The house rule is absolute: services
  raise a `FrontOfficeError` subclass, never return `None`, `[]` or an `"❌ ..."`
  string that a caller cannot tell from a real answer. An empty list is a valid
  answer; a failed request is not. Look for `except ...: return None`, bare
  `return []` on an error path, and error text returned as data.
- **Swallowed exceptions.** `except Exception: pass`, a log with no re-raise on
  a path the caller needs to know about, `raise X` without `from e`.
- **Naive datetimes.** `datetime.now()` or `date.today()` without a timezone for
  anything persisted or compared. Basketball must anchor to `PACIFIC`; a local
  clock shifts the day boundary. A platform timestamp parsed anywhere but
  `parse_utc` can come out naive, and comparing it to an aware `now` raises.
- **Date label versus instant.** `ScheduledGame.date` is a label for window
  tests, not a moment. Comparing it to an aware datetime, or reading a game's
  `status` for a game that is not today, is the mistake this distinction exists
  to prevent.
- **Cross-platform player identity.** Yahoo and Sleeper share no identifier, so
  the join is by normalized name in `competitions/nba/projections.py` and
  `competitions/nba/form.py`. An ambiguous surname must resolve to *nothing*,
  and an unmatched player must carry no line rather than borrowing someone
  else's. Any "first match wins" fallback is a correctness finding.
- **Cache freshness.** A `Freshness` predicate that cannot express what the
  endpoint actually does — a TTL where the rule is "until the next game tips
  off"; a failed fetch stored as though it were an answer; a key that collides
  across leagues or seasons.
- **Boundary conditions.** Empty rosters, a competition with zero leagues, a
  week before the season starts, off-by-one on gameweek and matchup numbering.
- **Type escape hatches.** `Any`, `# type: ignore`, `cast` — each is a place the
  checker was overruled. Cluster them; a cluster usually marks a real modelling
  gap.
- **Resource handling.** Unclosed files or sessions, missing `finally`, a
  temporary file left behind on the error path.

## 2. Security

Frame findings as defensive maintenance: name the pattern, the impact, and the
remediation. No runnable misuse examples.

**Handling rule: never copy a secret value into a finding or a plan.** Name the
`file:line` and the credential type only ("Yahoo client secret at `settings.py:36`"),
and always recommend rotation — a committed secret is burned even after deletion.

- **Credential hygiene.** Anything that would put `.env`, `.yahoofantasy` or a
  cache directory into a commit; a secret read through `os.getenv` at a call
  site instead of the `settings` singleton; a value logged, rendered or returned
  by an API route. `config/env_file.py` is the only sanctioned writer and it
  accepts only keys `AppSettings` declares.
- **Prompt content.** Prompts carry the user's roster and leagues. They are
  exported only under `LOGFIRE_CAPTURE_PROMPTS`; anything that logs or exports
  prompt text unconditionally is a finding.
- **Untrusted third-party data.** Every platform response and every cached file
  is data from outside. Look for it reaching an interpreter, a filesystem path,
  or a model prompt without validation — and for cached content being treated as
  instructions.
- **Input contracts.** FastAPI routes that trust a request body without a schema,
  path parameters interpolated into a filesystem path or an upstream URL.
- **OAuth.** `ensure_authorized` exists so non-interactive callers never trigger
  a browser flow implicitly. Any implicit OAuth trigger is a finding.
- **Dependency posture.** `uv run pip-audit` read-only if available. Report only
  critical/high advisories affecting reachable code.
- **Error detail exposure.** Stack traces or upstream error bodies returned to
  the client. Requests' own exceptions escaping as a 500 rather than going
  through `yahoo.translate` is the known instance of this shape.

## 3. Performance

Algorithmic and architectural wins, not micro-optimizations.

- **Repeated work.** The same upstream fetch or the same expensive parse
  performed per request where a cache entry or a hoisted computation belongs.
- **Serial where parallel is safe.** `make_request` is the only Yahoo fetch that
  parallelises safely; `cached_many` exists for the batch case. A season of
  weekly requests run one after another is the canonical instance.
- **Cache sizing.** A large upstream payload stored whole where only a few fields
  are read — the Sleeper catalog and season stats are both trimmed before
  caching for exactly this reason.
- **TTLs that do not match reality.** Too short and the app hammers an API that
  asked for politeness; too long and it shows stale data. Sleeper asks for its
  catalog at most once a day; a finished season never changes again.
- **Front end.** The entry bundle has a hard budget checked by the build. Watch
  for a heavyweight dependency pulled in for trivial use, motion imported
  outside `lib/motion.ts` (which lands the library in the entry bundle), and
  anything that should be deferred past first paint.
- **CI.** Redundant steps, missing caching, a gate that duplicates another.

## 4. Tests

The goal is not a percentage — it is *which untested code is dangerous*. See the
`review-tests` skill for the quality bar; this category is about coverage shape.

- Map the paths that matter — the provider joins, the cache freshness rules, the
  error translation, the engine's headline overwrite — and check which have zero
  or trivial coverage.
- High churn with no tests is the top refactor risk; flag as "characterization
  tests first" and order it before any plan that touches that code.
- Coverage is gated at 95%, which means the number tells you nothing about
  quality. Look for tests written to move it: no assertion, `assert x is not
  None`, a loop asserting something the types already guarantee.
- Hermeticism: anything reaching the network or real credentials without the
  `integration` marker, or writing outside `tmp_path`.
- Over-marking: a test marked `integration` that did not need to be is a test
  `just check` never runs.

## 5. Tech debt & architecture

- **Layering violations.** The rule points inward only: `domain/` imports nothing
  else in the package, `application/` imports only `domain/`, adapters implement
  ports, `bootstrap.py` alone names a concrete implementation. An adapter
  imported from `domain/` or `application/`, or an engine constructing its own
  collaborator instead of taking it as a required argument, is a finding.
- **Competition or platform specifics in the wrong place.** Anything
  competition-specific in `domain/`, `application/` or the inbound adapters. A
  provider named in an entry point rather than in a `CompetitionEntry`.
- **The second instance.** The repo's stated rule is to extract on the second
  occurrence, not the third. Look for logic written twice that belongs in
  `platforms/` (infrastructure), `competitions/` (cross-competition policy), or
  `domain/` (rules that hold regardless).
- **Naming drift.** `<Platform>Client`, `<Platform><Competition>Provider`,
  `<Verb>Engine`, `<What>Error`; **roster** for a set of players a manager owns,
  everywhere. Under `competitions/<competition>/`, the provider file is named for
  the platform owning the league, and other platforms are role-named helpers —
  never a second file named after a platform.
- **Front-end structure.** `panels/` holds one page each; anything used by a
  second caller belongs in `components/ui/`. A card, table, loading state or
  control reimplemented per panel is the specific drift this rule exists to stop.
  Color from a raw Tailwind palette utility instead of a semantic token cannot
  follow a palette change.
- **God modules.** Files an order of magnitude larger than the median. A provider
  outgrowing one file has a prescribed split: `week.py`, `league.py`, `prompt.py`.
- **Dead code.** Settings nothing reads, `just` recipes for files nothing writes,
  cache keys nothing fetches, commented-out blocks.

## 6. Dependencies

- Anything imported directly but not declared directly — the rule forbids relying
  on a transitive dependency.
- Unbounded or one-sided version constraints; the convention is
  `>=X.Y.Z,<NEXT_MAJOR` on both ends, then `just lock`.
- An `instrument_*` call without its matching extra: it imports fine and raises
  at call time.
- Major-version lag where staying behind has real cost (EOL, security cutoff).
- Two dependencies solving the same problem.
- `uv.lock` drift against `pyproject.toml`; `web/pnpm-lock.yaml` against
  `package.json`.

## 7. DX & tooling

- A gate that exists locally but not in CI, or vice versa — CI runs the same
  `just` recipes, so adding one to the `justfile` should extend CI.
- POSIX-only commands or `strftime` dash-modifiers (`%-d`) in tooling: both are
  glibc-only and this project supports Windows. Hardcoded `.venv/bin/...` paths
  for the same reason.
- Setup steps in `README.md` that are wrong or incomplete; an environment
  variable nothing declares, or a declared one nothing documents.
- Slow feedback: a gate that takes minutes, a test suite that could be narrowed.

## 8. Docs

Lowest default priority — flag only where absence has a concrete cost.

- `README.md` describing behavior the code no longer has. Stale is worse than
  missing, and the repo requires README updates in the same commit as a
  behavior, command, dependency or environment change.
- `AGENTS.md` over its 200-line cap, or a rule in it the code contradicts.
- A `CLAUDE.md` that is a real file rather than a symlink to its sibling — two
  real files drift and each tool reads a different one.

## 9. Direction — features and where to take this next

Forward-looking. **Grounding rule:** every suggestion must cite evidence from
this repo. A suggestion that could apply to any project ("add AI", "add dark
mode" — it has five palettes already) is noise.

- **Unfinished intent:** TODO clusters around one theme, a settings field nothing
  reads, a model field no panel renders, half-built modules.
- **Stated but undelivered:** anything `README.md` promises without code behind
  it; a competition wired into the registry with no provider depth.
- **Surface asymmetries:** a capability one competition has and the others don't
  — a view, a stat, a prompt section — where the shared models already carry the
  data. The registry is keyed by (competition, platform), so "the same
  competition on a second platform" is often nearly free.
- **The adjacent possible:** what the existing shape makes disproportionately
  cheap. A new competition is a provider, a prompt template and one
  `CompetitionEntry`. A capability the ports already express costs a `bootstrap`
  wiring and nothing else.

Direction findings use the standard format with two adaptations: **Impact** is
user value (who wants this and why now), and **Confidence** reflects how grounded
the evidence is, not certainty it is the right call. Effort estimates are
coarser here; say so. Selected direction findings usually become a design or
spike plan, not a build-everything plan.

---

## Finding format

Every finding, from every category and every subagent, comes back in this shape:

```markdown
### [CATEGORY-NN] Short imperative title

- **Evidence**: `path/file.py:123` — one sentence on what is there. (Repeat per
  location; 2–5 strongest, note "and ~N similar sites" if widespread.)
- **Impact**: What goes wrong, concretely. "Every scout run refetches the 3MB
  catalog", not "suboptimal".
- **Effort**: S (hours) / M (a day-ish) / L (multi-day) — for the *fix*,
  including tests.
- **Risk**: What the fix could break; LOW/MED/HIGH plus one line why.
- **Confidence**: HIGH (read the code, certain) / MED (strong signal, needs
  verification) / LOW (smell, needs investigation). LOW-confidence findings get
  an "investigate" plan, not a "fix" plan.
- **Fix sketch**: 1–3 sentences. Not the plan — just enough to judge effort.
```

## Prioritization rubric

Order by **leverage = impact ÷ effort, discounted by confidence and fix-risk**.
Tiebreakers:

1. Anything that unblocks other findings (a verification baseline,
   characterization tests) floats up.
2. HIGH-confidence security findings float above equivalent-leverage
   non-security findings.
3. Prefer findings with a clean verification story — `just check` either passes
   or it doesn't, and executors succeed at those.
4. "Not worth doing" is a valid verdict. Record it with one line of reasoning so
   nobody re-audits it.
