"""
Complete AI — organizational entity graph.

Built strictly from stored rows (never hardcoded). Edges connect incidents
to deployments, deployments to PRs/commits, PRs to repos, tickets to
incidents, and Slack messages to whatever entity ids they mention.
"""

from __future__ import annotations

import networkx as nx

from models import Commit, Deployment, Document, Incident, Message, PullRequest, Repository, Ticket, WikiPage


def build_graph(session) -> nx.DiGraph:
    g = nx.DiGraph()

    for r in session.query(Repository).all():
        g.add_node(r.repo_id, kind="Repository", label=r.name)

    for c in session.query(Commit).all():
        g.add_node(c.commit_id, kind="Commit", label=c.message[:60])
        if c.repo_id in g:
            g.add_edge(c.commit_id, c.repo_id, relation="commit_in")

    for p in session.query(PullRequest).all():
        g.add_node(p.pr_id, kind="PullRequest", label=p.title)
        if p.repo_id in g:
            g.add_edge(p.pr_id, p.repo_id, relation="pr_in")
        if p.commit_id in g:
            g.add_edge(p.pr_id, p.commit_id, relation="commit_from")

    for d in session.query(Deployment).all():
        g.add_node(d.deployment_id, kind="Deployment", label=d.deployment_id)
        if d.repo_id in g:
            g.add_edge(d.deployment_id, d.repo_id, relation="deploys")
        for pr_id in d.pr_ids:
            if pr_id in g:
                g.add_edge(d.deployment_id, pr_id, relation="deployment_contains")

    for i in session.query(Incident).all():
        g.add_node(i.incident_id, kind="Incident", label=i.title)
        if i.service in g:
            g.add_edge(i.incident_id, i.service, relation="affects")
        if i.related_deployment_id and i.related_deployment_id in g:
            g.add_edge(i.incident_id, i.related_deployment_id, relation="started_after")

    for t in session.query(Ticket).all():
        g.add_node(t.ticket_id, kind="Ticket", label=t.title)
        if t.related_incident_id and t.related_incident_id in g:
            g.add_edge(t.ticket_id, t.related_incident_id, relation="discusses")
        if t.related_pr_id and t.related_pr_id in g:
            g.add_edge(t.ticket_id, t.related_pr_id, relation="discusses")

    for d in session.query(Document).all():
        g.add_node(d.doc_id, kind="Document", label=d.title)
        for mention in d.mentions:
            if mention in g:
                g.add_edge(d.doc_id, mention, relation="governs")

    for w in session.query(WikiPage).all():
        g.add_node(w.page_id, kind="WikiPage", label=w.title)
        for mention in w.mentions:
            if mention in g:
                g.add_edge(w.page_id, mention, relation="documents")

    for m in session.query(Message).all():
        node_id = m.message_id
        g.add_node(node_id, kind="Message", label=m.content[:60])
        if m.thread_id:
            g.add_edge(node_id, f"thread:{m.thread_id}", relation="part_of_thread")
        for mention in m.mentions:
            if mention in g:
                g.add_edge(node_id, mention, relation="discusses")

    return g


def trace_upstream(session, entity_id: str) -> list[str]:
    g = build_graph(session)
    if entity_id not in g:
        return []
    return list(nx.ancestors(g, entity_id))


def trace_downstream(session, entity_id: str) -> list[str]:
    g = build_graph(session)
    if entity_id not in g:
        return []
    return list(nx.descendants(g, entity_id))


def neighbors_of(session, entity_id: str) -> dict:
    g = build_graph(session)
    if entity_id not in g:
        return {"predecessors": [], "successors": []}
    return {
        "predecessors": [{"id": n, **g.nodes[n]} for n in g.predecessors(entity_id)],
        "successors": [{"id": n, **g.nodes[n]} for n in g.successors(entity_id)],
    }


def graph_snapshot(session) -> dict:
    """Full node/edge dump for the UI's context graph panel."""
    g = build_graph(session)
    nodes = [{"id": n, **data} for n, data in g.nodes(data=True)]
    edges = [
        {"source": u, "target": v, "relation": data.get("relation")} for u, v, data in g.edges(data=True)
    ]
    return {"nodes": nodes, "edges": edges}
