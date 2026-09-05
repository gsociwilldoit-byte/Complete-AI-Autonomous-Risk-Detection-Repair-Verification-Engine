# Complete AI

**One Organizational Intelligence That Can Find, Understand, Do, and Verify Work**

Complete AI is one persistent agent (`CompleteAgent`) with one evolving
`TaskState`. Give it an objective — no repo name, no file, no incident id —
and it decides for itself whether it needs to search organizational
knowledge, inspect a repository, run tests, edit code, or all of the above,
interleaved, until an independent verifier confirms the work is actually
done.

```
UNDERSTAND <-> SEARCH <-> REASON <-> ACT <-> OBSERVE <-> VERIFY <-> CONTINUE
```

There is one tool registry (`agent/tool_registry.py`) shared by every
search, git, filesystem, test-execution, and workflow tool. There is no
`discover_agent/` handing off to a separate `slash_agent/`.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Generate a fresh simulated organization (seeded, reproducible)
python -m simulator.organization --seed 42

# Launch (serves both the API and the frontend from one origin)
uvicorn api.main:app --port 8001
# open http://localhost:8001
```

## The signature demo

Type exactly this into the command center, with nothing else:

> Checkout latency increased after last week's release. Find out why and fix it.

Watch it: search Slack/tickets/incidents/docs with no hints → find the
incident → trace incident → deployment → PR → repo through the context
graph → provision a sandbox copy of the real repo → run the real test suite
→ read the config → make a first fix that clears one test but breaks a
*different* one → search the runbook instead of guessing again → revise the
fix from that evidence → get both tests passing → have an independent
verifier re-run everything from scratch → prepare a PR draft, which pauses
for human approval because opening a PR is an external write.

Two more demos ship in the same organization:
- **Pure knowledge**: "Why does payment-router use this fallback strategy?" — cited answer, zero code touched.
- **Mixed task**: "Customers are reporting duplicate confirmation emails after retries. Investigate and resolve it." — a different repo, a different bug class, same one agent.

## Prove nothing is hardcoded

```bash
python -m simulator.organization --seed 42
python -m evaluation.run --seed 42

python -m simulator.organization --seed 927
python -m evaluation.run --seed 927
```

Both seeds produce a genuinely different organization (different bad
timeout values, different message wording, different entity ids), and both
show the same qualitative result: a search-only baseline solves ~33% (it can
answer the knowledge question but structurally cannot act), a coding-only
baseline that skips organizational search solves 0% (it can never discover
the legacy-client compatibility bound, which only exists in a runbook), and
Complete AI solves 100% by combining both.

## Run the tests

```bash
pip install -r requirements.txt
python -m simulator.organization --seed 42
pytest
```

`pytest` alone (from the repo root, no arguments) is sufficient —
`pyproject.toml` scopes discovery to `tests/` and excludes `demo_org/`,
so it will not try to collect the simulated demo-org repos' own test
files (a real bug found by execution: those repos each have their own
`tests/test_error_schema.py` with no `__init__.py`, which collide on
module name across repos and crash a plain `pytest` before it runs a
single real test, if discovery isn't scoped).

**A real ordering gotcha, also found by execution**: `python -m
evaluation.run --seed <N>` regenerates the *canonical*
`demo_org/workspace` fixture with whatever seed you pass it — running it
with a different seed than the one you last used leaves that directory
in a different (still entirely valid, just different) state. The test
suite itself does **not** depend on this — it generates its own
fully-isolated workspace via `tests/conftest.py`'s `seeded_org` fixture,
in a separate temp directory, unaffected by whatever `demo_org/workspace`
currently contains. If you want to go back to a specific known seed for
manual poking around afterward, just re-run
`python -m simulator.organization --seed 42`.

## The general diagnose-edit-test loop

Engineering used to be the one part of this project that wasn't actually
general: `agent/reasoning.py` dispatched through a hardcoded
`REPO_PROCEDURES` table (`checkout-service` -> a hand-written timeout
procedure, `notification-service` -> a hand-written idempotency
procedure), and any repo outside that table returned "no investigation
procedure available." That table is gone. `investigate()` now calls
`agent/general_loop.py::run_general_loop` unconditionally, for any repo:

1. Runs the repo's real test suite for a baseline.
2. Structurally analyzes whatever fails (`agent/failure_analysis.py`) —
   real AST-based import resolution of the failing test's own source
   (not a hardcoded bug name) to find which file/symbols it implicates,
   plus regex extraction of the values pytest's own assertion-rewriting
   already rendered.
3. Tries four general repair strategies, each triggered only by a
   structural pattern, never a repo name: a numeric value outside a
   documented bound; a `+1`/`-1` adjustment inverting a boundary
   comparison; a returned dict's keys not matching what the test's own
   assertion states; the same function called twice in its own test with
   the same argument, expecting a guarded side effect (synthesizes a real
   per-argument idempotency guard from scratch).
4. If a *different* test starts failing after an edit, extracts new
   search terms from *that* failure and searches organizational knowledge
   with them — genuine self-correction, not a hardcoded fallback.
5. On convergence via a resolved numeric bound, writes a new regression
   test file named after whichever symbol was actually fixed.
6. Caps at 4 attempts; if nothing converges, closes honestly as
   `INSUFFICIENT_EVIDENCE` with every hypothesis tried logged.

**Proof this is genuinely general, not three procedures in a trenchcoat**:
a fourth bug — an off-by-one in `payment-router`'s retry policy — was
added to the simulator with its own real failing test, described nowhere
in this codebase's comments until after the general loop already existed.
The same loop solves it with zero new code path
(`tests/test_upgrade_features.py::test_no_repo_keyed_dispatch_table_exists_anywhere`
greps the actual source and fails the build if a repo-keyed dispatch
table or a new `investigate_<repo>` method is ever reintroduced).

## The Slash Reviewer

## Multi-repo execution

One objective can genuinely span more than one repository. In this demo
org, "Standardize error response schema across all services" identifies
that `checkout-service`, `payment-router`, and `notification-service` all
return a differently-shaped error dict (`{"error": ...}` vs
`{"failure_reason": ...}` vs `{"reason": ...}`), and:

- gives each repository its own sandbox, its own branch, its own commit
- runs each one through the same 5-dimension review and merge decision
  independently
- then runs a **real cross-service contract check** — it actually invokes
  each repository's live `to_error_response()` function via subprocess
  after the fix and compares the returned key sets, rather than trusting
  each repo's own test result in isolation

This surfaced a real design bug during development: adding a schema test to
every repo initially broke the *existing* single-repo flagship demos,
because their pass/fail checks scanned the whole `tests/` directory —
which now always included the unrelated schema test. Fixed by building a
principled scoped verifier (`verify_scoped_fix`) that checks "did this
task's specific fix work" and "were no *new* regressions introduced,"
rather than conflating that with "is this repository free of every other,
unrelated bug." The same fix was applied retroactively to the original
single-repo checkout/notification flows, which is a strictly better
verifier than what existed before.

## The Event Center — zero-prompt entry

Two events sit in `SimEvent` from the moment the organization is
generated — a GitHub CI failure and a ticket auto-assignment — exactly
like every other seeded entity, with no human input. Clicking **DISPATCH**
(`POST /api/events/{id}/dispatch`) runs the *exact same*
`CompleteAgent.run()` loop as any typed objective, with the objective
derived from the event instead of typed by a person. A dispatched event is
marked consumed and cannot be dispatched twice (verified: real 409 on
re-dispatch). This is the "three doors" concept — free-text objective
(Slack-mention-shaped), a bare ticket id (ticket-auto-assignment-shaped),
and now a dispatchable event (CI-trigger-shaped) — without needing a real
Slack or GitHub integration.



Every generated patch goes through a real multi-dimensional review
(`tools/review.py`) before anything is proposed externally:

- **Five dimensions**: bug detection (fresh test re-run), security (real
  regex checks for hardcoded credentials, `eval`/`exec`, unsafe
  deserialization, `shell=True`, SQL string concatenation), design system
  (real `ruff`/`black` results against the Engineering Standards wiki page),
  internationalization (heuristic scan for hardcoded user-facing strings),
  and pre-mortem (a per-bug-class heuristic — e.g. flags changes to shared
  mutable state that lack a concurrency test).
- **A real AI filtering pass**: every dimension's raw findings go through a
  filter that discards low-confidence matches — a security pattern matched
  inside a test file or comment, for example — before anything is scored.
  This is genuine filtering logic against the real diff text, not a
  fabricated ratio.
- **Real severity scoring** (HIGH/MEDIUM/LOW) computed from the filtered,
  actionable findings.
- **A real zero-human auto-merge decision** (`decide_merge_policy`): a
  clean review with no actionable findings and a small, scoped diff opens
  the PR and posts the ticket update immediately, no approval step in
  between. Anything else — including a genuinely-found pre-mortem risk on a
  shared-state change — routes to a human, with the real finding as the
  stated reason.
- **A real, queryable merge-rate stat** (`/api/stats/merge-rate`): "N of M
  engineering tasks merged with zero human review," computed from actual
  persisted task history, not a hardcoded ratio.

In this demo organization, the checkout-service timeout fix (a small,
bounded config correction) genuinely auto-merges, while the
notification-service idempotency fix (a change to shared in-process state)
genuinely does not — the same reviewer code path produces different, honest
outcomes because the underlying risk is different.


```bash
pytest tests/ -q
```

30 tests covering: seeded generation, real injected bugs (genuinely failing
pytest runs, not just metadata), hybrid retrieval + provenance, the entity
graph, sandbox isolation and path-escape refusal, the full signature-demo
loop including search-triggered-by-test-failure interleaving, the safety
gate's four tiers, the verifier's structural independence from the agent's
own claims, and ground-truth isolation (`agent/`, `tools/`, and
`knowledge/` statically never import the hidden bug labels).

## Real bugs found and fixed while building this

Documented here rather than swept under the rug:

1. **`process_checkout`'s own dict-merge order** silently overwrote
   `"status": "success"` with the gateway client's internal
   `"status": "authorized"`, making the reproduction test structurally
   unable to pass regardless of the timeout value. Not the intentional bug —
   a bug in the test fixture itself, caught by actually running the tests
   rather than trusting that the code "looked right."
2. **Python bytecode caching**: two edits to the same file with equal-length
   values (`"5000"` -> `"1450"`), applied within the same wall-clock second,
   could leave size+mtime unchanged from Python's cache-invalidation
   perspective — silently re-running tests against stale compiled bytecode.
   Fixed with `PYTHONDONTWRITEBYTECODE=1` plus an explicit `__pycache__`
   purge on every edit. There's a regression test for this specific bug
   (`tests/test_sandbox.py::test_bytecode_cache_does_not_mask_rapid_edits`).
3. **`GitPython`'s `index.add(["."])` does not behave like real
   `git add .`** — it tracked `.git`'s own internal files while leaving the
   actual source untracked, which corrupted every `git diff` with binary
   index noise instead of the real code change. Fixed by shelling out to
   the real `git add -A` via `repo.git.add(A=True)`.

## Repository layout

```
complete-ai/
├── agent/          # the one agent runtime, state, reasoning, verifier, safety gate, tool registry
├── tools/          # search / git / engineering (edit+test+run) / workflow tools — one registry
├── knowledge/      # hybrid retrieval + NetworkX entity graph
├── sandbox/        # per-task isolated workspace (real git repos, real subprocess execution)
├── simulator/      # seeded organization generator: repos with real bugs, Slack, docs, tickets, incidents, logs
├── evaluation/      # search-only vs coding-only vs Complete AI, across task buckets
├── api/            # FastAPI backend (also serves the frontend, same origin)
├── frontend/        # single-file live workspace UI
├── tests/           # pytest suite (30 tests)
├── demo_org/         # generated repos + per-task sandboxes (gitignored in practice)
├── models.py / db.py # SQLAlchemy models + session management
├── docker-compose.yml, Dockerfile, .env.example
└── README.md
```

## Correctness, hallucination risk, and token cost

Three questions any technical reviewer should ask, answered with evidence
rather than assertion:

**"How do I know the debugging conclusions aren't AI hallucinations?"**
Because, by default, no LLM is ever consulted to reach them.
`ReferenceReasoningPolicy` — the policy this project ships and runs on —
is fully deterministic Python: TF-IDF retrieval, rule-based hypothesis
selection, and real subprocess execution (`pytest`, `ruff`, `black`, `git`).
There is no model in the loop generating "what probably happened." The
proof is testable, not just claimed:
`test_debugging_conclusion_is_deterministic_across_independent_runs` runs
the identical objective twice, from two independent fresh sandboxes, and
asserts the root cause, the fix diff, the review verdict, and the merge
decision are byte-identical both times. An LLM free-forming over a large
context window would not reliably reproduce that; a deterministic rule
engine re-executing real code does, by construction.

**"What does this cost to run?"** For every task type — engineering,
multi-repo, ticket-only, event-dispatched — the answer is measured, not
estimated: **0 LLM tokens**, because the reference policy never calls an
LLM at all. This is surfaced directly in the UI's Demo Audit panel (a
green "LLM tokens used: 0 / reference policy — no LLM call made" cell) and
locked in by `test_zero_llm_usage_by_default`. The only place an LLM is
ever optionally consulted is `LLMReasoningPolicy`, used only when
`ANTHROPIC_API_KEY` is set, and only to rephrase an already-fully-computed
knowledge-only answer — never to select tools, attribute a root cause, or
approve a merge. When that path *is* active, real usage (`input_tokens`,
`output_tokens`, an estimated cost from the actual Anthropic API response)
is captured and shown, not guessed.

**"Do internal tools already do this?"** Search-and-answer platforms and
autonomous coding agents both exist as separate categories. What's being
tested here isn't "does search exist" or "does an agent that edits code
exist" — it's whether *fusing* them into one continuous loop is what
demonstrably solves a task neither can solve alone. The evaluation harness
(`evaluation/run.py`) measures this directly rather than asserting it:
across two different seeded organizations, a search-only baseline solves
~33% of tasks (it can answer but structurally can't act), a coding-only
baseline that skips organizational search solves 0% (it can act but never
discovers the constraint that only exists in a runbook), and the unified
agent solves 100%. That comparison is the actual differentiation claim,
and it's re-runnable against a fresh seed on demand.

## Runs without an API key

`ReferenceReasoningPolicy` is fully deterministic and requires no LLM — this
is the default. If `ANTHROPIC_API_KEY` is set, `LLMReasoningPolicy` may help
phrase the final knowledge-only answer more naturally, but it never
fabricates evidence, never chooses which files to edit, and never bypasses
the sandbox/test-execution pipeline — deterministic infrastructure still
controls permissions, execution, and verification.

## Known limitations of this prototype

- Two repo-specific investigation procedures are implemented
  (`checkout-service`'s timeout regression, `notification-service`'s
  idempotency bug) rather than a fully general code-repair strategy for
  arbitrary unseen bug classes — analogous to how FullCircle AI's reference
  policy handles a fixed set of financial hypothesis types. A genuinely
  novel bug class in a fourth repo would correctly report
  `INSUFFICIENT_EVIDENCE` rather than hallucinate a fix.
- `update_ticket` exists as a real, safety-gated tool but the reference
  policy's investigation flow doesn't currently call it (only
  `prepare_pull_request` is invoked) — a contained addition, not a design
  gap.
- The evaluation harness's `coding_only` baseline uses a simple keyword
  guess at which repo is affected rather than a separate, fully-independent
  coding agent implementation.
