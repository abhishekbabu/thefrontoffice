# Handoff Plan Template

Every plan is written for an executor model with **zero context**: it has not
seen the advisor session, the audit, the other plans, or any prior conversation.
It may be smaller and cheaper. Assume it follows explicit instructions well and
fills gaps, recovers from ambiguity, and knows when to stop badly.

Three properties make a plan executable by a weaker model:

1. **Self-contained context** — paths, excerpts, conventions and commands are all
   in the file.
2. **Verification gates** — every step ends with a command and its expected
   result, so the executor never has to *judge* whether it succeeded.
3. **Hard boundaries and escape hatches** — an explicit out-of-scope list, and
   "STOP and report" conditions instead of improvising when reality differs.

File naming: `plans/NNN-short-slug.md`, numbered in recommended execution order.
`plans/` is gitignored — plans are working artifacts, and this repo keeps prose
documentation to `README.md` and `AGENTS.md`.

---

## Template

```markdown
# Plan NNN: <Imperative title — what will be true after this plan>

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in `plans/README.md`, unless a
> reviewer dispatched you and said they maintain the index.
>
> **Drift check (run first)**: `git diff --stat <planned-at SHA>..HEAD -- <in-scope paths>`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code first; on a mismatch, treat it
> as a STOP condition.

## Status

- **Priority**: P1 | P2 | P3
- **Effort**: S | M | L
- **Risk**: LOW | MED | HIGH
- **Depends on**: plans/NNN-*.md (or "none")
- **Category**: correctness | security | perf | tests | tech-debt | dependencies | dx | docs | direction
- **Planned at**: commit `<short SHA>`, <YYYY-MM-DD>

## Why this matters

Two to five sentences: the problem, its concrete cost, and what improves when
this lands. Intent is what lets the executor make a correct judgment call when a
detail turns out to be slightly off.

## Current state

The facts the executor needs, inlined — never "as discussed" or "see the audit":

- Each relevant file with one line on its role:
  - `src/thefrontoffice/adapters/outbound/platforms/sleeper/client.py` — the
    catalog fetch and trim (lines 220–255)
- Short excerpts of the code as it exists today, with `file:line` markers, so
  the executor can confirm it is looking at the right thing.
- The conventions that apply, with a pointer to one exemplar:
  "Errors are raised, never returned — see `domain/errors.py` and its use in
  `platforms/sleeper/client.py:60-75`. Match it."
- The specific `AGENTS.md` rules this work must honor, **quoted**. The executor
  has not read them, and several are non-obvious: aware UTC only, `PACIFIC` for
  basketball, roster as the word for a manager's players, semantic color tokens
  only, dependencies pointing inward.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `just install` | exit 0 |
| Everything CI runs | `just check` | exit 0, coverage ≥ 95% |
| Tests, filtered | `just test "-k <expr>"` | all pass |
| Types | `uv run pyrefly check` | 0 errors |
| Lint + format | `just fmt` then `just check` | exit 0 |
| Front end | `just check-web` | exit 0, first-paint bundle within budget |

(Exact commands verified during recon, not guessed. Omit rows the plan does not
need — a backend-only plan does not run `just check-web`.)

## Suggested executor toolkit

(Optional — include only when a relevant skill exists. Skip otherwise.)

- `adding-a-competition` — when the plan wires a new competition or platform.
- `review-tests` — when the plan adds or changes tests.
- `thermo-nuclear-code-quality-review` — when the plan is a large refactor whose
  main risk is making the code harder to maintain.

## Scope

**In scope** (the only files to modify):
- `src/thefrontoffice/adapters/outbound/platforms/sleeper/client.py`
- `tests/test_sleeper_client.py`

**Out of scope** (do NOT touch, even though they look related):
- `platforms/cache.py` — shared by three platforms; a change here is a separate
  plan with its own blast radius.
- Anything under `domain/` — this is an adapter concern and the layering rule
  points inward only.

## Git workflow

- Branch from `main`: `fix/<slug>` (prefixes in use: `feat/`, `fix/`, `chore/`,
  `test/`). The `no-commit-to-branch` hook blocks committing to `main` directly.
- Conventional commit subjects. `just check` must pass before committing; the
  pre-commit hooks run the same gates, so a commit that skips them fails anyway.
- Update `README.md` in the same commit if behavior, commands, dependencies or
  environment variables change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: <imperative title>

Precisely what to do, naming exact files and symbols. Include the target code
shape where it is load-bearing.

**Verify**: `<command>` → <expected output>

### Step 2: ...

(Each step independently verifiable. Order them so the tree is never broken
between steps: add the new path, switch callers, then remove the old one.)

## Test plan

- New tests, in which file, covering which cases — name them: the happy path,
  the specific regression this plan prevents, the named edge cases.
- Which existing test to model structurally: "follow `tests/test_cache.py` —
  fakes by keyword, one behavior per test, names that read as sentences".
- New code needs tests in the same commit, and coverage is gated at 95%.
- **Verification**: `just test "-k <expr>"` → all pass, including N new tests.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `just check` exits 0
- [ ] New tests for <X> exist and pass
- [ ] `grep -rn "<old pattern>" src/` returns no matches
- [ ] No files outside the in-scope list are modified (`git status --short`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report — do not improvise — if:

- The code at the "Current state" locations does not match the excerpts (the
  repo has drifted since this plan was written).
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to need an out-of-scope file.
- Coverage falls below 95% and the only way you can see to restore it is a test
  that asserts nothing meaningful.
- The assumption "<key assumption>" turns out to be false.

## Maintenance notes

For whoever owns this code next:

- What future changes interact with this.
- What a reviewer should scrutinize.
- Anything deliberately deferred out of this plan, and why.
```

---

## Index file: `plans/README.md`

Written once by the advisor after all plans, updated by executors:

```markdown
# Implementation Plans

Generated by the improve skill on <date>. Execute in the order below unless
dependencies say otherwise. Read each plan fully before starting, honor its STOP
conditions, and update your row when done.

## Execution order & status

| Plan | Title | Priority | Effort | Depends on | Status |
|------|-------|----------|--------|------------|--------|
| 001  | ...   | P1       | S      | —          | TODO   |

Status values: TODO | IN PROGRESS | DONE | BLOCKED (one-line reason) | REJECTED
(one-line rationale — fixed independently, or the approach was abandoned)

## Dependency notes

- 002 requires 001 because <reason>.

## Findings considered and rejected

- <finding>: not worth doing because <one line>. (So nobody re-audits it.)
```

## Quality bar — check before finishing each plan

- Could a model that has never seen this repo execute this with only the plan
  file and the repo? If a step needs knowledge from the advisor session, inline
  that knowledge.
- Is every verification a command with an expected result, not a judgment call?
- Does every step name exact files and symbols, not "the relevant module"?
- Are the STOP conditions specific to this plan's real risks, not boilerplate?
- Would a reviewer reading only "Why this matters" and "Done criteria"
  understand what they are approving?
- No secret values anywhere — locations and credential types only.
- Is "Planned at" filled in, and do the drift-check paths match the Scope
  section?
