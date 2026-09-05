from agent.reasoning import classify_task_type
from agent.runtime import CompleteAgent
from agent.safety_gate import evaluate_action
from agent.verifier import verify_engineering_task, verify_knowledge_task


def test_signature_demo_full_loop(session):
    agent = CompleteAgent(session)
    state = agent.run("Checkout latency increased after last week's release. Find out why and fix it.")
    assert state.task_type == "engineering"
    phases = [a.phase for a in state.audit_trail]
    for required in ("UNDERSTAND", "SEARCH", "RUN", "EDIT", "TEST", "VERIFY", "CLOSE"):
        assert required in phases, f"expected phase {required} in {phases}"
    assert state.status in ("VERIFIED_COMPLETE", "APPROVAL_REQUIRED", "PARTIALLY_COMPLETE")
    assert state.final_verdict is not None
    assert state.final_verdict["verdict"] in ("VERIFIED_COMPLETE", "PARTIALLY_COMPLETE")


def test_interleaving_search_triggered_by_test_failure(session):
    """Core acceptance criterion: a test failure must be able to trigger a
    fresh SEARCH, not just another blind EDIT."""
    agent = CompleteAgent(session)
    state = agent.run("Checkout latency increased after last week's release. Find out why and fix it.")
    phases = [a.phase for a in state.audit_trail]
    first_test_idx = phases.index("TEST")
    later_search_after_test = any(p == "SEARCH" for p in phases[first_test_idx:])
    assert later_search_after_test, "expected a SEARCH phase after a TEST phase (interleaving)"


def test_knowledge_only_task_makes_no_code_changes(session):
    agent = CompleteAgent(session)
    state = agent.run("Why does payment-router use this fallback strategy?")
    assert state.task_type == "knowledge_only"
    assert state.code_changes == []
    assert state.final_answer is not None
    assert "[" in state.final_answer  # has at least one citation marker


def test_classify_task_type_knowledge_vs_engineering():
    assert classify_task_type("Why does payment-router use a fallback?") == "knowledge_only"
    assert classify_task_type("Fix the checkout latency bug") == "engineering"


def test_safety_gate_tiers():
    assert evaluate_action("search_organization")["verdict"] == "ALLOWED"
    assert evaluate_action("edit_file")["verdict"] == "ALLOWED"
    assert evaluate_action("update_ticket")["verdict"] == "APPROVAL_REQUIRED"
    assert evaluate_action("deploy_to_production")["verdict"] == "DENIED"


def test_verifier_independent_of_agent_claim():
    """Structural check: the verifier functions take no 'agent says done' flag."""
    import inspect

    sig = inspect.signature(verify_engineering_task)
    assert "claimed_done" not in sig.parameters
    sig2 = inspect.signature(verify_knowledge_task)
    assert "claimed_done" not in sig2.parameters


def test_knowledge_verifier_requires_multiple_sources():
    result = verify_knowledge_task([{"source": "document", "content": "x"}])
    assert result["verdict"] == "INSUFFICIENT_EVIDENCE"
    result2 = verify_knowledge_task(
        [
            {"source": "document", "content": "x"},
            {"source": "slack", "content": "y"},
        ]
    )
    assert result2["verdict"] == "VERIFIED_COMPLETE"


def test_task_state_persists_across_iterations(session):
    """No restart-reasoning-from-scratch: evidence accumulated early must
    still be present in the final state."""
    agent = CompleteAgent(session)
    state = agent.run("Checkout latency increased after last week's release. Find out why and fix it.")
    assert len(state.evidence) > 0
    assert len(state.tool_history) > 0 or len(state.audit_trail) > 5
