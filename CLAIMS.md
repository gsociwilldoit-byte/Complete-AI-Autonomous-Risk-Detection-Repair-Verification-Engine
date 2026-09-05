# CLAIMS.md

Every claim this project or its README/UI makes, classified honestly.
This file exists specifically to prevent accidental overclaiming — if a
capability isn't classified here, treat it as unverified.

Categories: **REAL** (genuinely works, verified by an executable test or
direct reproduction), **SIMULATED** (behaves like the real thing inside
this project's seeded organization, but doesn't call an external
service), **OPTIONAL INTEGRATION** (real when configured, inert/absent
otherwise), **LIMITATION** (a known, disclosed gap).

## Core engineering loop

| Claim | Status | Evidence |
|---|---|---|
| General failure-driven repair loop (no per-repo dispatch table) | **REAL** | `agent/general_loop.py`; `tests/test_upgrade_features.py::test_no_repo_bug_type_mapping_exists_anywhere` greps source and fails the build if a repo-keyed table is reintroduced |
| Structural pytest-failure parsing via real AST import resolution | **REAL** | `agent/failure_analysis.py`; directly verified against real pytest output for 4 independent bug classes |
| Solves a genuinely unseen bug/repo with no repo-specific code path | **REAL** | payment-router's off-by-one retry bug was added *after* the general loop existed, described nowhere else in the codebase; solved with zero new dispatch entry |
| Dynamic repository/package discovery (no `PACKAGE_NAMES` lookup) | **REAL** | `agent/project_inspector.py`; verified against all 3 real repos |
| Structural risk inference (no `REPO_BUG_TYPES` lookup) | **REAL** | `tools/review.py::_check_pre_mortem`; catches module-level mutable state / new I/O from the diff's actual shape, verified on a completely novel repo/function name never seen elsewhere in the codebase |
| Independent verifier, identity-aware regression detection | **REAL** | `agent/verifier.py`; test proves a count-based check would miss a regression that the identity-aware check catches |
| New regression test synthesized after a numeric-bound fix | **REAL** | general loop writes and runs a new test file, named after whichever symbol it actually fixed |
| Real git branch + commit (not simulated) | **REAL** | actual `git checkout -b` / `git commit`, real SHA returned; verified with zero global git config on the host |
| Real `ruff`/`black` execution | **REAL** | actual subprocess calls to the real tools, not string matching |
| Cross-service contract check (multi-repo) | **REAL**, narrow scope | discovers a single-argument function in a module whose name contains "error" and compares real return shapes across repos; this is a heuristic contract-discovery mechanism, not a general OpenAPI/schema-based contract system (see Limitations) |
| Sandbox isolation between tasks | **REAL** (workspace isolation), **NOT** container/OS-level security isolation | each task gets its own copied directory (`sandbox/workspace.py`); path traversal, symlink escape, and prefix-collision are defended against (`Path.resolve()` + `is_relative_to()`, tested); there is no container, no non-root user enforcement, no cgroup/seccomp boundary — a malicious command run inside a sandbox has the same OS-level privileges as the server process |

## Organizational knowledge

| Claim | Status | Evidence |
|---|---|---|
| Cross-source search (Slack/GitHub/Drive/Wiki/Jira/Logs/Incidents) | **SIMULATED** | all 7 sources are seeded by `simulator/`, not live integrations; retrieval itself (TF-IDF ranking, source-type filtering) is real code exercised against that seeded data |
| Provenance on every evidence item (source, id, timestamp) | **REAL** | `knowledge/retrieval.py`; every returned item carries this |
| Context/entity graph | **REAL** data, **partial** use | `/api/organization/graph` returns real node/edge data built from the same seeded entities; the frontend renders it as a real interactive graph (Complete-AI-upgrade session); the graph is not yet consulted *during reasoning* (e.g. "trace failure → deployment → PR → incident" is not implemented as a reasoning step) |
| Claim-level provenance / contradiction detection | **NOT IMPLEMENTED** | evidence is source-level, not claim-level; no contradiction-detection pass exists |

## Reviewer / governance

| Claim | Status | Evidence |
|---|---|---|
| "5-dimension reviewer" | **REAL, deterministic** — not AI | bug_detection/security/design_system/internationalization/pre_mortem are all regex/AST/structural checks; no model is consulted. Calling this "AI review" anywhere is a labeling error this project has made and should not repeat. |
| AI-filtering of low-confidence findings | **REAL, deterministic** — not AI | a real filtering pass (test-file/comment matches discarded) exists and is exercised in real runs; "AI filtering" is a misnomer for what is deterministic confidence-tagging logic |
| Auto-merge / zero-human-review path | **REAL** | `agent/safety_gate.py::evaluate_merge_action` is the single, central, auditable authority for this decision (fixed in this session — previously bypassed in one orchestration branch); proven with real DB writes on approval |
| "PR opened" / "PR merged" | **SIMULATED** | no real GitHub API call; a local artifact's status field flips from `draft` to `opened`. No GitHub integration exists. |
| Approval gate with human-in-the-loop | **REAL** | `/api/tasks/{id}/approvals`; verified live: approving a ticket update genuinely writes a new status/comment to the ticket store; double-approval correctly rejected (409) |

## Model-assisted reasoning

| Claim | Status | Evidence |
|---|---|---|
| Optional LLM-assisted answer phrasing | **OPTIONAL INTEGRATION** | `agent/reasoning.py::LLMReasoningPolicy`; only active if `ANTHROPIC_API_KEY` is set. **No API key is configured in this environment** — every live run in this build uses the deterministic reference policy exclusively. |
| Zero-LLM-token deterministic mode | **REAL** | `test_zero_llm_usage_by_default`; every engineering/multi-repo/knowledge task in this build reports 0 tokens, verified, not merely defaulted |
| Real token/cost accounting when the LLM path IS active | **REAL mechanism, untested against a live model** | `LLMReasoningPolicy` captures the actual `usage` field the Anthropic API returns; this code path has not been exercised against a real API call in this session (no key available) |
| Hybrid Reasoner→Runtime→Verifier architecture (LLM proposes, deterministic runtime proves) | **NOT IMPLEMENTED** | the architecture described in later planning documents (structured `NEED_EVIDENCE`/`PATCH_PROPOSAL` contract, shadow sandbox, hypothesis reassessment) has not been built; the current LLM integration point is narrower (answer phrasing only) |

## Event-driven entry

| Claim | Status | Evidence |
|---|---|---|
| Event Center — zero-prompt task dispatch | **REAL mechanism, SIMULATED sources** | `SimEvent` rows are seeded, not received from a real webhook/GitHub/ticketing system; dispatching one runs the real, same `CompleteAgent.run()` loop, and re-dispatch is correctly rejected (verified) |
| Generic event adapter (webhook/GitHub/ticketing/chat sources) | **NOT IMPLEMENTED** | only the simulator source exists |

## Evaluation

| Claim | Status | Evidence |
|---|---|---|
| Multi-seed evaluation comparing search-only / coding-only / hybrid | **REAL**, small scale | `evaluation/run.py`; genuinely executes each baseline and computes solve rate from real outcomes, not fabricated numbers |
| Held-out benchmark (50–100 tasks, ablations, unseen repos/bug families) | **NOT IMPLEMENTED AT THAT SCALE** | current evaluation covers 3 seeded task types across 2 seeds; a 4th repo/bug-family (payment-router's off-by-one) was added specifically to test generalization, but this is not a formal held-out split of dozens of tasks |
| Ablation studies (remove graph/verifier/reviewer, measure degradation) | **NOT IMPLEMENTED** | no ablation harness exists |

## Security / auth

| Claim | Status | Evidence |
|---|---|---|
| Path traversal / symlink escape defense | **REAL** | `sandbox/workspace.py`; 6 explicit attack-shaped tests pass (`../`, absolute path, prefix-collision sibling directory, symlink escape, invalid repo id, and a control test proving legitimate access still works) |
| API authentication / authorization / roles | **NOT IMPLEMENTED** | the API has no auth layer; anyone who can reach it can create tasks and approve actions. This is a real, disclosed gap, not a "demo-only" caveat that's actually fine — a production deployment must not expose this API without adding one. |
| Container-based execution isolation | **NOT IMPLEMENTED** | see "Sandbox isolation" above; this is filesystem-copy isolation, not a security boundary |
| Secrets redaction in logs | **NOT AUDITED** | no dedicated redaction pass exists; not known to leak secrets in this demo (no real secrets are ever present in the seeded data), but this has not been tested against a real-secrets scenario |

## Terminology this project has previously used loosely, now corrected here

- "AI review" / "AI filtering" → these are **deterministic** mechanisms; the word "AI" describing them is a labeling error, not a description of a model call.
- "Real GitHub merge" → never claimed to be a real GitHub merge; the correct phrase is a **local, policy-approved merge simulation**.
- "100% solved" (for a 3-task demo) → should read **"N of N demo scenarios verified"**, not a percentage implying a benchmark.
