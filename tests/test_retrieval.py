from knowledge.graph import build_graph, trace_downstream
from knowledge.retrieval import search_all


def test_search_returns_provenance_fields(session):
    results = search_all(session, "checkout latency", top_k=5)
    assert results
    for r in results:
        assert "source" in r and "source_id" in r and "content" in r
        assert "relevance" in r


def test_cross_source_search_finds_multiple_source_types(session):
    results = search_all(session, "checkout latency increased after last week's release", top_k=10)
    sources = {r["source"] for r in results}
    assert len(sources) >= 2, f"expected evidence from multiple source types, got {sources}"


def test_search_is_not_just_highest_similarity_dump(session):
    """Sanity: an irrelevant query should return few or no results, not everything."""
    results = search_all(session, "zzz_nonexistent_term_qqq", top_k=10)
    assert len(results) <= 3


def test_graph_built_from_stored_data_only(session):
    g = build_graph(session)
    assert g.number_of_nodes() > 0
    from models import Repository

    repo_ids = {r.repo_id for r in session.query(Repository).all()}
    assert repo_ids.issubset(set(g.nodes))


def test_graph_traces_incident_to_repo(session):
    from models import Incident

    inc = session.query(Incident).filter(Incident.service == "checkout-service").first()
    if inc is None:
        return
    downstream = trace_downstream(session, inc.incident_id)
    assert "checkout-service" in downstream


def test_freshness_field_present_for_documents(session):
    results = search_all(session, "gateway timeout", top_k=5, sources=["drive"])
    assert results
    for r in results:
        assert r["timestamp"] is not None
