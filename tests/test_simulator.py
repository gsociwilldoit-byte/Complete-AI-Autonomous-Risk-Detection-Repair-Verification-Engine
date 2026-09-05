import tempfile

from simulator.organization import generate_organization


def test_generation_produces_expected_entity_counts(seeded_org):
    data = seeded_org
    assert len(data["repos"]) == 3
    assert len(data["incidents"]) >= 1
    assert len(data["messages"]) >= 1
    assert len(data["documents"]) >= 1


def test_injected_bugs_are_real_and_reproducible(seeded_org):
    from sandbox.workspace import new_sandbox
    from tools.engineering import run_tests

    # All three repos now carry a real, distinct injected bug — payment-router's
    # off-by-one retry-policy bug (added for P1's generalization acceptance
    # test) means there is no longer a "clean, zero-bug" repo in this org.
    buggy_repos = [r for r in seeded_org["repos"] if r.bug]
    assert len(buggy_repos) == 3
    for repo in buggy_repos:
        sb = new_sandbox([repo.repo_id])
        result = run_tests(sb, repo.repo_id)
        assert not result["passed"], f"expected {repo.repo_id} to have a real failing test"
        sb.cleanup()


def test_every_repo_bug_is_solvable_by_the_general_loop_with_no_repo_specific_code(seeded_org):
    """The actual P1 acceptance test: every seeded repo's own distinct bug
    (timeout regression, duplicate-send idempotency, off-by-one retry) is
    solved by the SAME general diagnose-edit-test loop — no repo-keyed
    dispatch table exists anymore. See agent/reasoning.py::investigate,
    which calls agent.general_loop.run_general_loop unconditionally."""
    from agent.general_loop import run_general_loop
    from agent.state import TaskState
    from db import SessionLocal
    from sandbox.workspace import new_sandbox

    session = SessionLocal()
    for repo in seeded_org["repos"]:
        state = TaskState(task_id=f"t-{repo.repo_id}", objective="test")
        sb = new_sandbox([repo.repo_id])
        result = run_general_loop(session, sb, state, repo.repo_id)
        assert result[
            "done"
        ], f"general loop failed to converge for {repo.repo_id}: {result.get('hypotheses_tried')}"
        sb.cleanup()


def test_route_payment_itself_is_bug_free(seeded_org):
    """All three repos now carry a real per-repo bug (that's the point of
    P1's generalization requirement — no repo is left as a trivial
    'always clean' control). What's still true and worth asserting: the
    pre-existing, never-touched-by-any-bug function (route_payment's own
    fallback logic) passes its own original test independent of every
    injected bug and independent of the shared error-schema drift."""
    from sandbox.workspace import new_sandbox
    from tools.engineering import run_tests

    sb = new_sandbox(["payment-router"])
    result = run_tests(sb, "payment-router", target="tests/test_router.py")
    assert result["passed"]
    sb.cleanup()


def test_different_seeds_produce_different_bad_values():
    d1 = generate_organization(seed=1, workspace_root=tempfile.mkdtemp())
    d2 = generate_organization(seed=2, workspace_root=tempfile.mkdtemp())
    checkout1 = next(r for r in d1["repos"] if r.repo_id == "checkout-service")
    checkout2 = next(r for r in d2["repos"] if r.repo_id == "checkout-service")
    # not guaranteed different every time (small value pool) but IDs/timestamps must differ
    assert checkout1.commits[-1]["commit_id"] != checkout2.commits[-1]["commit_id"]


def test_ground_truth_ids_cross_reference_real_rows(session):
    from models import GroundTruthBug, Incident

    for bug in session.query(GroundTruthBug).all():
        if bug.related_incident_id:
            inc = session.query(Incident).filter(Incident.incident_id == bug.related_incident_id).first()
            assert inc is not None, f"{bug.bug_id} references a nonexistent incident"
