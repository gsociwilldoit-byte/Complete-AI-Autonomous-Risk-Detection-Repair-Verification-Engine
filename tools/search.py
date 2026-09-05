"""Complete AI — search and knowledge tools (one registry, no separate 'search agent')."""

from __future__ import annotations

from knowledge.graph import neighbors_of
from knowledge.graph import trace_downstream as _trace_downstream
from knowledge.graph import trace_upstream as _trace_upstream
from knowledge.retrieval import search_all as _search_all
from knowledge.retrieval import search_by_entity_id as _search_by_entity_id


def search_organization(session, query: str, sources: list[str] | None = None, top_k: int = 8) -> list[dict]:
    return _search_all(session, query, top_k=top_k, sources=sources)


def search_slack(session, query: str, top_k: int = 6) -> list[dict]:
    return _search_all(session, query, top_k=top_k, sources=["slack"])


def search_docs(session, query: str, top_k: int = 6) -> list[dict]:
    return _search_all(session, query, top_k=top_k, sources=["drive", "wiki"])


def search_drive(session, query: str, top_k: int = 6) -> list[dict]:
    return _search_all(session, query, top_k=top_k, sources=["drive"])


def search_wiki(session, query: str, top_k: int = 6) -> list[dict]:
    return _search_all(session, query, top_k=top_k, sources=["wiki"])


def search_github(session, query: str, top_k: int = 6) -> list[dict]:
    return _search_all(session, query, top_k=top_k, sources=["pull_request", "commit"])


def search_tickets(session, query: str, top_k: int = 6) -> list[dict]:
    return _search_all(session, query, top_k=top_k, sources=["ticket"])


def search_incidents(session, query: str, top_k: int = 6) -> list[dict]:
    return _search_all(session, query, top_k=top_k, sources=["incident"])


def search_logs(session, query: str, top_k: int = 10) -> list[dict]:
    return _search_all(session, query, top_k=top_k, sources=["log"])


def find_related(session, entity_id: str) -> list[dict]:
    return _search_by_entity_id(session, entity_id)


def trace_entity_upstream(session, entity_id: str) -> list[str]:
    return _trace_upstream(session, entity_id)


def trace_entity_downstream(session, entity_id: str) -> list[str]:
    return _trace_downstream(session, entity_id)


def get_entity_neighbors(session, entity_id: str) -> dict:
    return neighbors_of(session, entity_id)
