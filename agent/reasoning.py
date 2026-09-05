"""
Complete AI — reasoning policies.

ReferenceReasoningPolicy is fully deterministic and requires no LLM — this
is what the project runs on by default. It classifies the objective's task
type, then either synthesizes a cited answer from retrieved evidence
(knowledge-only) or hands off to the general failure-driven repair loop
(agent/general_loop.py), which searches, inspects, edits, and re-tests
code in the sandbox until the repository's real test suite passes, using
structural analysis of the failure rather than any repository-specific
knowledge.

LLMReasoningPolicy is an optional enhancement (used only when
ANTHROPIC_API_KEY is set) that may help phrase the synthesized answer or
choose between ambiguous next steps, but never fabricates evidence and
never bypasses the sandbox/test-execution pipeline.
"""

from __future__ import annotations

import os

from logging_config import get_logger

_log = get_logger("reasoning")

KNOWLEDGE_QUESTION_MARKERS = ("why ", "why does", "why is", "explain", "how does", "what is", "what causes")
ACTION_MARKERS = (
    "fix",
    "resolve",
    "implement",
    "investigate and",
    "find out why",
    "add validation",
    "duplicate",
    "increased",
    "latency",
    "broken",
    "failing",
    "bug",
)


def classify_task_type(objective: str) -> str:
    text = objective.lower()
    has_question_marker = any(m in text for m in KNOWLEDGE_QUESTION_MARKERS)
    has_action_marker = any(m in text for m in ACTION_MARKERS)
    if has_action_marker:
        return "engineering"
    if has_question_marker:
        return "knowledge_only"
    return "engineering"  # default to attempting real work over a bare answer


MULTI_REPO_MARKERS = (
    "across all services",
    "across every service",
    "across services",
    "all repos",
    "all repositories",
    "every service",
    "every repo",
    "coordinated across",
)


def is_multi_repo_objective(text: str) -> bool:
    lowered = text.lower()
    return any(m in lowered for m in MULTI_REPO_MARKERS)


class ReferenceReasoningPolicy:
    name = "reference"

    # ---- knowledge-only path --------------------------------------------------------------

    def answer_from_evidence(self, objective: str, evidence: list[dict]) -> str:
        if not evidence:
            return "No organizational evidence was found for this objective."
        lines = [f"Regarding: {objective}\n"]
        by_source = {}
        for e in evidence:
            by_source.setdefault(e["source"], []).append(e)
        order = ["document", "pull_request", "commit", "slack", "incident", "ticket", "log"]
        for source in order:
            items = by_source.get(source)
            if not items:
                continue
            label = {
                "document": "Documentation",
                "pull_request": "Pull request",
                "commit": "Commit",
                "slack": "Slack discussion",
                "incident": "Incident",
                "ticket": "Ticket",
                "log": "Logs",
            }[source]
            for item in items[:2]:
                snippet = item["content"].strip().replace("\n", " ")[:220]
                lines.append(f"- [{label}: {item['source_id']}] {snippet}")
        return "\n".join(lines)

    # ---- engineering path: per-repository investigation procedures ------------------------

    # ---- engineering path: general failure-driven repair -----------------------------------
    #
    # Generic diagnose/edit/test loop (agent/general_loop.py) driven by
    # structural analysis of whatever test actually fails, for any
    # repository — no repository-name dispatch, no per-repo procedure.

    def investigate(self, session, sandbox, state, repo_id: str):
        from agent.general_loop import run_general_loop

        return run_general_loop(session, sandbox, state, repo_id)


class LLMReasoningPolicy(ReferenceReasoningPolicy):
    """Optional LLM-enhanced policy: same tool pipeline, but may help phrase
    the final synthesized knowledge-only answer more naturally. Never
    invents evidence and never skips the sandbox/test-execution path.

    Real token/cost accounting: every call records the actual usage the
    Anthropic API reports (input_tokens, output_tokens), not an estimate of
    what "should" have been used. self.last_usage is None until a call
    actually happens — which, in this default configuration (no API key),
    is never, for the entire lifetime of the process. Every debugging
    decision (which repo, which fix, which review verdict, which merge
    decision) is made by ReferenceReasoningPolicy's deterministic code path
    regardless of whether this class is active; the LLM, when configured,
    only ever touches the wording of an already-fully-computed answer."""

    name = "llm_enhanced"

    # Illustrative Anthropic per-token rates (USD per token) — update from
    # https://docs.claude.com/en/docs/about-claude/pricing for the exact
    # current rate of whichever model is configured. Kept as named constants
    # rather than inline literals so the estimate is auditable, not hidden.
    _RATE_INPUT_PER_TOKEN = 3.0 / 1_000_000
    _RATE_OUTPUT_PER_TOKEN = 15.0 / 1_000_000

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key
        self.model = model
        self.last_usage: dict | None = None

    def answer_from_evidence(self, objective: str, evidence: list[dict]) -> str:
        import httpx

        base_answer = super().answer_from_evidence(objective, evidence)
        prompt = (
            "Rewrite the following evidence-grounded answer as 2-4 clear sentences. "
            "Do not add any fact not present in the evidence. Keep every citation marker "
            "like [Documentation: DOC-x] exactly as given.\n\n" + base_answer
        )
        try:
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            body = resp.json()
            text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
            usage = body.get("usage") or {}
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            self.last_usage = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "estimated_cost_usd": round(
                    input_tokens * self._RATE_INPUT_PER_TOKEN + output_tokens * self._RATE_OUTPUT_PER_TOKEN, 6
                ),
                "model": self.model,
            }
            return text.strip() or base_answer
        except Exception as ex:  # noqa: BLE001 — intentionally broad: any
            # failure of this OPTIONAL enhancement (timeout, HTTP error,
            # malformed JSON, unexpected response shape) must never crash a
            # task or block the already-fully-computed deterministic answer.
            # It must, however, be visible server-side rather than silently
            # swallowed, so a real outage doesn't look like "the LLM path
            # just quietly stopped enhancing answers."
            _log.warning(
                "LLM-enhanced answer rewrite failed (%s); falling back to the deterministic answer.",
                ex.__class__.__name__,
            )
            return base_answer


def get_reasoning_policy():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        return LLMReasoningPolicy(
            api_key=api_key, model=os.environ.get("COMPLETE_AI_LLM_MODEL", "claude-sonnet-4-6")
        )
    return ReferenceReasoningPolicy()
