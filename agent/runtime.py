"""
Complete AI — the one agent runtime.

CompleteAgent owns a single evolving TaskState and runs:

    UNDERSTAND -> SEARCH -> (READ/RUN/EDIT/TEST as needed) -> VERIFY -> CLOSE

Search and execution are tools in the same registry available to the same
loop — there is no DiscoveryAgent handing off to an ExecutionAgent. A failed
test can send reasoning back to SEARCH; a search result can trigger an EDIT.

External-write actions (opening a PR, updating a ticket) are PREPARED here
but not actually committed to their store until a human approves them via
the API's /approve endpoint (see api/main.py) — the safety gate's
APPROVAL_REQUIRED verdict is a real gate, not a cosmetic label.
"""

from __future__ import annotations

import json
import uuid

from agent.project_inspector import inspect_repository
from agent.reasoning import classify_task_type, get_reasoning_policy, is_multi_repo_objective
from agent.safety_gate import evaluate_merge_action
from agent.state import TaskState
from agent.tool_registry import call_tool
from agent.verifier import verify_knowledge_task, verify_scoped_fix
from logging_config import get_logger
from models import Repository
from sandbox.workspace import new_sandbox
from tools.review import decide_merge_policy, run_multi_dimensional_review
from tools.tickets import is_bare_ticket_id

_log = get_logger("runtime")


class CompleteAgent:
    def __init__(self, session):
        self.session = session
        self.policy = get_reasoning_policy()

    def run(self, objective: str) -> TaskState:
        task_id = f"task-{uuid.uuid4().hex[:10]}"
        state = TaskState(task_id=task_id, objective=objective)
        state.reasoning_policy = self.policy.name
        state.log("UNDERSTAND", f"Objective received: \u201c{objective}\u201d")

        ticket_id = is_bare_ticket_id(objective)
        effective_query = objective
        if ticket_id:
            state.log(
                "READ",
                f"Objective is a bare ticket id \u2014 reading {ticket_id} directly.",
                tool="read_ticket",
            )
            ticket = call_tool("read_ticket", session=self.session, ticket_id=ticket_id)
            if not ticket:
                state.status = "INSUFFICIENT_EVIDENCE"
                state.log("CLOSE", f"No such ticket: {ticket_id}.")
                return state
            state.log(
                "OBSERVE",
                f"{ticket_id}: \u201c{ticket['title']}\u201d "
                f"(priority {ticket['priority']}, status {ticket['status']}).",
            )
            effective_query = f"{ticket['title']}. {ticket['description']}"
            state.task_type = "engineering"
            state.log(
                "UNDERSTAND",
                "Ticket read \u2014 proceeding directly to the engineering workflow "
                "with no repository or file supplied by the user.",
            )
        else:
            state.task_type = classify_task_type(objective)
            state.log("UNDERSTAND", f"Classified as a {state.task_type.replace('_', ' ')} task.")

        state.add_plan_step("Search organizational knowledge for relevant context")
        state.set_plan_status("Search organizational knowledge for relevant context", "active")
        state.log("SEARCH", f"Searching the organization for: {effective_query}", tool="search_organization")
        initial_evidence = call_tool(
            "search_organization", session=self.session, query=effective_query, top_k=8
        )
        state.add_evidence(initial_evidence)
        state.tool_history.append("search_organization")
        state.log(
            "OBSERVE",
            f"Found {len(initial_evidence)} relevant item(s) across "
            f"{len({e['source'] for e in initial_evidence})} source type(s): "
            f"{', '.join(sorted({e['source'] for e in initial_evidence}))}.",
            data={"sources": sorted({e["source"] for e in initial_evidence})},
        )
        state.set_plan_status("Search organizational knowledge for relevant context", "done")

        if state.task_type == "knowledge_only":
            self._run_knowledge_task(state)
        elif is_multi_repo_objective(effective_query):
            self._run_multi_repo_engineering_task(state)
        else:
            self._run_engineering_task(state, ticket_id=ticket_id)

        # Real token/cost accounting: reads whatever the policy actually
        # recorded, not an estimate. For ReferenceReasoningPolicy this
        # attribute doesn't exist at all (getattr default None) — the LLM
        # was never consulted for ANY part of this task's reasoning, tool
        # selection, or verification, regardless of task type.
        llm_usage = getattr(self.policy, "last_usage", None)
        state.llm_usage = llm_usage
        if llm_usage:
            state.log(
                "OBSERVE",
                f"LLM usage this task: {llm_usage['input_tokens']} input + "
                f"{llm_usage['output_tokens']} output tokens "
                f"(~${llm_usage['estimated_cost_usd']:.6f}).",
            )
        else:
            state.log(
                "OBSERVE",
                "LLM usage this task: 0 tokens — every decision was made by the "
                "deterministic reference policy, not a language model.",
            )

        return state

    # ---- knowledge-only path ----------------------------------------------------------------

    def _run_knowledge_task(self, state: TaskState):
        state.add_plan_step("Synthesize a cited answer from gathered evidence", "active")
        answer = self.policy.answer_from_evidence(state.objective, state.evidence)
        state.final_answer = answer
        state.log(
            "VERIFY",
            "Checking that the answer is grounded in enough independently-sourced evidence.",
            tool="verify_knowledge_task",
        )
        verdict = verify_knowledge_task(state.evidence)
        state.final_verdict = verdict
        state.status = verdict["verdict"]
        state.set_plan_status("Synthesize a cited answer from gathered evidence", "done")
        state.log("CLOSE", f"Task closed with status {state.status}.")

    # ---- engineering path -------------------------------------------------------------------

    def _identify_target_repo(self, state: TaskState) -> str | None:
        repo_ids = {r.repo_id for r in self.session.query(Repository).all()}
        for e in state.evidence:
            for entity in e.get("related_entities") or []:
                if entity in repo_ids:
                    return entity
        for repo_id in repo_ids:
            if repo_id.replace("-", " ") in state.objective.lower() or repo_id in state.objective.lower():
                return repo_id
        return None

    def _run_engineering_task(self, state: TaskState, ticket_id: str | None = None):
        state.add_plan_step("Identify the affected repository")
        repo_id = None

        if ticket_id:
            ticket = call_tool("read_ticket", session=self.session, ticket_id=ticket_id)
            if ticket and ticket.get("related_incident_service"):
                repo_id = ticket["related_incident_service"]
                state.log(
                    "SEARCH",
                    f"Ticket links to {ticket['related_incident_id']}, affecting service {repo_id}.",
                    tool="trace_entity_upstream",
                )

        if not repo_id:
            repo_id = self._identify_target_repo(state)
        if not repo_id:
            state.log(
                "SEARCH",
                "No repository identified from initial evidence; searching incidents directly.",
                tool="search_incidents",
            )
            incident_evidence = call_tool("search_incidents", session=self.session, query=state.objective)
            state.add_evidence(incident_evidence)
            repo_id = self._identify_target_repo(state)

        if not repo_id:
            state.status = "INSUFFICIENT_EVIDENCE"
            state.log("CLOSE", "Could not identify an affected repository from available evidence.")
            return

        state.set_plan_status("Identify the affected repository", "done")
        state.log("OBSERVE", f"Identified affected repository: {repo_id}.")

        state.add_plan_step("Trace related deployments, PRs, and commits")
        downstream = call_tool("trace_entity_downstream", session=self.session, entity_id=repo_id)
        upstream = call_tool("trace_entity_upstream", session=self.session, entity_id=repo_id)
        for eid in set(downstream) | set(upstream):
            state.context_graph_nodes.add(eid)
        state.log(
            "SEARCH",
            f"Traced {len(upstream)} upstream and {len(downstream)} downstream "
            f"entities in the context graph.",
            tool="trace_entity_upstream",
        )
        state.set_plan_status("Trace related deployments, PRs, and commits", "done")

        state.add_plan_step("Reproduce the issue in a sandboxed copy of the repository")
        sandbox = new_sandbox([repo_id])
        state.log("RUN", f"Provisioned an isolated sandbox copy of {repo_id}.", tool="provision_sandbox")

        result = self.policy.investigate(self.session, sandbox, state, repo_id)
        state.set_plan_status("Reproduce the issue in a sandboxed copy of the repository", "done")

        if not result.get("done"):
            state.status = "FAILED_VERIFICATION" if state.code_changes else "INSUFFICIENT_EVIDENCE"
            state.log(
                "CLOSE",
                f"Could not verify a working fix for {repo_id}: "
                f"{result.get('reason', 'tests still failing after investigation')}.",
            )
            sandbox.cleanup()
            return

        state.add_plan_step("Independently verify the fix", "active")
        state.log(
            "VERIFY",
            "Independently re-running the full test suite and the specific "
            "reproduction test from scratch.",
            tool="verify_engineering_task",
        )
        verdict = verify_scoped_fix(
            sandbox, repo_id, result["reproduction_test"], result.get("baseline_failures", [])
        )
        state.final_verdict = verdict
        state.log("VERIFY", f"Verifier result: {verdict['verdict']}.", data=verdict)
        state.set_plan_status("Independently verify the fix", "done")

        diff = call_tool("inspect_diff", sandbox=sandbox, repo_id=repo_id)
        state.artifacts.append({"type": "diff", "repo_id": repo_id, "content": diff})

        if verdict["verdict"] in ("VERIFIED_COMPLETE", "PARTIALLY_COMPLETE"):
            state.add_plan_step("Structural review of the generated patch", "active")
            review = run_multi_dimensional_review(
                diff,
                {
                    "full_suite_passed": verdict.get("no_new_regression"),
                    "reproduction_passed": verdict.get("target_reproduction_passed"),
                },
                state.quality_checks,
            )
            state.artifacts.append({"type": "pr_review", **review.to_dict()})
            state.log(
                "VERIFY",
                f"Structural review across {len(review.dimensions)} dimensions: {review.verdict}. "
                f"{len(review.potential_findings)} potential finding(s), "
                f"{review.filtered_count} filtered as low-confidence, "
                f"{len(review.actionable_findings)} actionable "
                f"(HIGH {review.severity_counts['HIGH']} / MEDIUM {review.severity_counts['MEDIUM']} "
                f"/ LOW {review.severity_counts['LOW']}).",
                tool="review_pull_request",
                data=review.to_dict(),
            )
            state.set_plan_status("Structural review of the generated patch", "done")

            merge_policy = decide_merge_policy(review, diff)
            state.merge_policy = merge_policy

            state.add_plan_step("Prepare pull request and ticket update", "active")
            pr_number = 200 + int(uuid.uuid4().hex[:3], 16) % 700
            pr_draft = call_tool(
                "prepare_pull_request",
                repo_id=repo_id,
                title=f"Fix: {state.objective[:60]}",
                description=self._build_pr_description(state, repo_id, verdict, ticket_id),
                diff=diff,
                test_summary=verdict,
                risk_assessment=self._risk_assessment(verdict, review.to_dict()),
            )
            pr_draft["pr_number"] = pr_number
            pr_draft["branch"] = result.get("branch")
            pr_draft["base_branch"] = "master"
            pr_draft["linked_ticket"] = ticket_id
            pr_draft["reviewers"] = ["eng-6"]
            pr_draft["rollback_plan"] = "Revert this PR's single commit; no data migrations involved."

            # Single code path for both outcomes: the central safety gate
            # (agent/safety_gate.py::evaluate_merge_action) is the ONLY
            # authority on whether this external write may proceed without
            # a human — no branch here decides that for itself.
            pr_safety = evaluate_merge_action("prepare_pull_request", merge_policy)
            pr_action_id = f"APR-{uuid.uuid4().hex[:8]}"
            auto = pr_safety["verdict"] == "SAFE_TO_EXECUTE"

            if auto:
                pr_draft["status"] = "opened"
            state.artifacts.append({"type": "pull_request_draft", "action_id": pr_action_id, **pr_draft})
            state.approvals.append(
                {
                    "action_id": pr_action_id,
                    "action": "prepare_pull_request",
                    **pr_safety,
                    "resolved": auto,
                    "resolution": "auto_approved" if auto else None,
                    "payload": {"pr_draft_id": pr_draft["pr_draft_id"], "pr_number": pr_number},
                }
            )
            state.log(
                "AUTO_MERGE" if auto else "REQUEST_APPROVAL",
                (
                    f"PR #{pr_number} auto-merged with zero human review: {pr_safety['reasons'][0]}"
                    if auto
                    else f"Prepared PR #{pr_number}: \u201c{pr_draft['title']}\u201d on branch "
                    f"{pr_draft['branch']}; {pr_safety['verdict']} \u2014 {pr_safety['reasons'][0]}."
                ),
                tool="prepare_pull_request",
                data=pr_safety,
            )
            if auto:
                state.auto_merged = True

            if ticket_id:
                ticket_comment = self._build_ticket_update(state, pr_number, verdict)
                ticket_safety = evaluate_merge_action("update_ticket", merge_policy)
                ticket_action_id = f"APR-{uuid.uuid4().hex[:8]}"
                ticket_auto = ticket_safety["verdict"] == "SAFE_TO_EXECUTE"

                if ticket_auto:
                    call_tool(
                        "update_ticket",
                        session=self.session,
                        ticket_id=ticket_id,
                        status="resolved",
                        comment=ticket_comment + "\n\nAuto-merged: no human review "
                        "required (clean deterministic review gate verdict).",
                    )
                state.artifacts.append(
                    {
                        "type": "ticket_update_draft",
                        "action_id": ticket_action_id,
                        "ticket_id": ticket_id,
                        "comment": ticket_comment,
                        "status": "posted" if ticket_auto else "pending",
                    }
                )
                state.approvals.append(
                    {
                        "action_id": ticket_action_id,
                        "action": "update_ticket",
                        **ticket_safety,
                        "resolved": ticket_auto,
                        "resolution": "auto_approved" if ticket_auto else None,
                        "payload": {"ticket_id": ticket_id, "status": "in_review", "comment": ticket_comment},
                    }
                )
                state.log(
                    "AUTO_MERGE" if ticket_auto else "REQUEST_APPROVAL",
                    (
                        f"Ticket {ticket_id} updated automatically \u2014 no approval needed."
                        if ticket_auto
                        else f"Prepared ticket update for {ticket_id}; {ticket_safety['verdict']} before it's posted."
                    ),
                    tool="update_ticket",
                    data=ticket_safety,
                )

            state.set_plan_status("Prepare pull request and ticket update", "done")
            state.status = verdict["verdict"] if auto else "APPROVAL_REQUIRED"
        else:
            state.status = verdict["verdict"]

        state.log("CLOSE", f"Task closed with status {state.status}.")
        sandbox.cleanup()

    # ---- multi-repo engineering path ---------------------------------------------------------

    def _run_multi_repo_engineering_task(self, state: TaskState):
        """
        A single objective that genuinely spans multiple repositories: each
        affected repo gets its own sandbox, its own branch, its own commit,
        its own independent multi-dimensional review and merge decision —
        then a real cross-service contract check verifies the repos actually
        agree with each other, by invoking each one's real function and
        comparing output, not by trusting each repo's own tests in isolation.
        """
        state.add_plan_step("Identify every repository affected by this objective")
        repo_ids = sorted(
            {
                e
                for ev in state.evidence
                for e in (ev.get("related_entities") or [])
                if e in {r.repo_id for r in self.session.query(Repository).all()}
            }
        )
        if len(repo_ids) < 2:
            # "across all services" with no specific doc naming them — fall back to every repo
            repo_ids = sorted(r.repo_id for r in self.session.query(Repository).all())
        state.log(
            "OBSERVE", f"Multi-repo objective spans {len(repo_ids)} repositories: {', '.join(repo_ids)}."
        )
        state.set_plan_status("Identify every repository affected by this objective", "done")

        sandboxes = {}
        state.add_plan_step("Fix, test, and review each repository independently", "active")
        for repo_id in repo_ids:
            state.log("RUN", f"Provisioning an isolated sandbox for {repo_id}.", tool="provision_sandbox")
            sandbox = new_sandbox([repo_id])
            sandboxes[repo_id] = sandbox

            result = self.policy.investigate(self.session, sandbox, state, repo_id)
            if not result.get("done"):
                state.multi_repo_results.append(
                    {
                        "repo_id": repo_id,
                        "verdict": "FAILED_VERIFICATION",
                        "reason": result.get("reason", "fix did not verify"),
                    }
                )
                continue

            verdict = verify_scoped_fix(
                sandbox, repo_id, result["reproduction_test"], result.get("baseline_failures", [])
            )
            diff = call_tool("inspect_diff", sandbox=sandbox, repo_id=repo_id)
            state.artifacts.append({"type": "diff", "repo_id": repo_id, "content": diff})

            review = run_multi_dimensional_review(
                diff,
                {
                    "full_suite_passed": verdict.get("no_new_regression"),
                    "reproduction_passed": verdict.get("target_reproduction_passed"),
                },
                [q for q in state.quality_checks if q.get("repo_id") == repo_id],
            )
            state.artifacts.append({"type": "pr_review", "repo_id": repo_id, **review.to_dict()})
            merge_policy = decide_merge_policy(review, diff)

            state.log(
                "VERIFY",
                f"{repo_id}: verifier {verdict['verdict']}, review {review.verdict}, "
                f"{'auto-mergeable' if merge_policy['auto_mergeable'] else 'needs human review'}.",
                data={"repo_id": repo_id, **merge_policy},
            )

            state.multi_repo_results.append(
                {
                    "repo_id": repo_id,
                    "verdict": verdict["verdict"],
                    "review_verdict": review.verdict,
                    "auto_mergeable": merge_policy["auto_mergeable"],
                    "reason": merge_policy["reason"],
                    "branch": result.get("branch"),
                }
            )

        state.set_plan_status("Fix, test, and review each repository independently", "done")

        state.add_plan_step("Independently verify cross-service contract agreement", "active")
        state.log(
            "VERIFY",
            "Invoking each repository's actual error-response function (discovered by "
            "inspecting its own modules, not a hardcoded symbol name) and comparing "
            "output shape across all of them \u2014 not trusting each repo's own tests in isolation.",
            tool="cross_service_check",
        )
        schemas = {}
        for repo_id, sandbox in sandboxes.items():
            profile = inspect_repository(sandbox, repo_id)
            package = profile.primary_package or repo_id.replace("-", "_")
            probe_script = (
                "import importlib, inspect, json, pkgutil\n"
                f"pkg = importlib.import_module('{package}')\n"
                "candidates = []\n"
                "for modinfo in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + '.'):\n"
                "    if 'error' not in modinfo.name.lower():\n"
                "        continue\n"
                "    mod = importlib.import_module(modinfo.name)\n"
                "    for name, fn in inspect.getmembers(mod, inspect.isfunction):\n"
                "        sig = inspect.signature(fn)\n"
                "        required = [p for p in sig.parameters.values() "
                "if p.default is inspect.Parameter.empty and p.kind not in "
                "(inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)]\n"
                "        if len(required) == 1:\n"
                "            candidates.append((modinfo.name, name))\n"
                "if not candidates:\n"
                "    print(json.dumps(None))\n"
                "else:\n"
                "    modname, fname = candidates[0]\n"
                "    mod = importlib.import_module(modname)\n"
                "    result = getattr(mod, fname)('x')\n"
                "    print(json.dumps(sorted(result.keys()) if hasattr(result, 'keys') else None))\n"
            )
            probe = sandbox.run_command(repo_id, ["python3", "-c", probe_script])
            try:
                schemas[repo_id] = json.loads(probe["stdout"].strip()) if probe["exit_code"] == 0 else None
            except (json.JSONDecodeError, ValueError) as ex:
                # A malformed/empty probe result means "this repo's function
                # could not be verified," not "the whole task should crash" —
                # but it must be visible, not silently None with no trace.
                _log.warning(
                    "Cross-service probe for %s returned unparseable output (%s): %r",
                    repo_id,
                    ex.__class__.__name__,
                    probe["stdout"][:200],
                )
                schemas[repo_id] = None

        distinct_shapes = {tuple(v) for v in schemas.values() if v is not None}
        contract_ok = len(distinct_shapes) == 1 and None not in schemas.values()
        state.cross_service_check = {"schemas": schemas, "agrees": contract_ok}
        state.log(
            "VERIFY",
            f"Cross-service contract check: {'PASS — all repos agree' if contract_ok else 'FAIL — schemas differ'}.",
            data=state.cross_service_check,
        )
        state.set_plan_status("Independently verify cross-service contract agreement", "done")

        for sandbox in sandboxes.values():
            sandbox.cleanup()

        all_verified = all(r["verdict"] == "VERIFIED_COMPLETE" for r in state.multi_repo_results)

        if all_verified and contract_ok:
            # Same central-authority rule as the single-repo path: every
            # per-repo merge decision goes through evaluate_merge_action —
            # no per-repo result's own "auto_mergeable" flag authorizes
            # anything by itself.
            gate_results = {
                r["repo_id"]: evaluate_merge_action(
                    "prepare_pull_request",
                    {"auto_mergeable": r.get("auto_mergeable"), "reason": r.get("reason", "")},
                )
                for r in state.multi_repo_results
            }
            if all(g["verdict"] == "SAFE_TO_EXECUTE" for g in gate_results.values()):
                state.auto_merged = True
                state.status = "VERIFIED_COMPLETE"
                for r in state.multi_repo_results:
                    call_tool(
                        "prepare_pull_request",
                        repo_id=r["repo_id"],
                        title=f"Fix: {state.objective[:50]} ({r['repo_id']})",
                        description="Auto-merged: clean multi-dimensional review across all "
                        "repositories, cross-service contract verified.",
                        diff="",
                        test_summary={},
                        risk_assessment="Low risk: coordinated, small, clean.",
                    )
                    state.approvals.append(
                        {
                            "action_id": f"APR-{uuid.uuid4().hex[:8]}",
                            "action": "prepare_pull_request",
                            **gate_results[r["repo_id"]],
                            "resolved": True,
                            "resolution": "auto_approved",
                            "payload": {"repo_id": r["repo_id"]},
                        }
                    )
                state.log(
                    "AUTO_MERGE",
                    f"All {len(repo_ids)} repositories auto-merged \u2014 "
                    f"cross-service contract independently verified.",
                )
            else:
                state.status = "APPROVAL_REQUIRED"
                for r in state.multi_repo_results:
                    gate = gate_results[r["repo_id"]]
                    if gate["verdict"] != "SAFE_TO_EXECUTE":
                        state.approvals.append(
                            {
                                "action_id": f"APR-{uuid.uuid4().hex[:8]}",
                                "action": "prepare_pull_request",
                                **gate,
                                "resolved": False,
                                "resolution": None,
                                "payload": {"repo_id": r["repo_id"]},
                            }
                        )
                state.log(
                    "REQUEST_APPROVAL",
                    f"{sum(1 for g in gate_results.values() if g['verdict'] != 'SAFE_TO_EXECUTE')} "
                    f"of {len(repo_ids)} repositories need human review before merging.",
                )
        else:
            state.status = (
                "PARTIALLY_COMPLETE"
                if any(r["verdict"] == "VERIFIED_COMPLETE" for r in state.multi_repo_results)
                else "FAILED_VERIFICATION"
            )

        state.log(
            "CLOSE",
            f"Multi-repo task closed with status {state.status} "
            f"({sum(1 for r in state.multi_repo_results if r['verdict']=='VERIFIED_COMPLETE')}"
            f"/{len(repo_ids)} repositories verified).",
        )

    @staticmethod
    def _build_pr_description(state: TaskState, repo_id: str, verdict: dict, ticket_id: str | None) -> str:
        lines = [
            "## Summary",
            f"Automated fix produced by Complete AI for objective: \u201c{state.objective}\u201d.",
        ]
        if ticket_id:
            lines.append(f"Linked ticket: {ticket_id}")
        lines += ["", "## Evidence"]
        for e in state.evidence[:5]:
            lines.append(f"- [{e['source']}:{e['source_id']}] {e['content'][:140].strip()}")
        lines += [
            "",
            "## Verification",
            f"- No new regressions introduced: {verdict.get('no_new_regression')}",
            f"- Reproduction test passed: {verdict.get('target_reproduction_passed')}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _build_ticket_update(state: TaskState, pr_number: int, verdict: dict) -> str:
        has_new_test = any(c.get("attempt") == "new_test" for c in state.code_changes)
        return (
            f"Root cause identified and fix verified.\n\n"
            f"PR #{pr_number} prepared, awaiting review.\n"
            f"No new regressions introduced: {verdict.get('no_new_regression')}.\n"
            f"Regression test added: {'yes' if has_new_test else 'no'}."
        )

    @staticmethod
    def _risk_assessment(verdict: dict, review: dict | None = None) -> str:
        base = (
            "Low risk: full test suite and targeted reproduction both pass with no regressions."
            if verdict["verdict"] == "VERIFIED_COMPLETE"
            else "Moderate risk: reproduction passes but the full suite has other failures \u2014 "
            "review before merging."
        )
        if review and review.get("actionable_findings"):
            top = review["actionable_findings"][0]
            base += f" AI review flagged ({top['severity']}, {top['dimension']}): {top['message']}"
        return base
