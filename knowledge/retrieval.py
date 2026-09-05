"""
Complete AI — hybrid retrieval.

Keyword + local TF-IDF semantic retrieval across every organizational
source (Slack messages, documents, tickets, incidents, logs, PRs, commits).
No external embedding API required — consistent with "must work without an
API key." Every result carries full provenance (source, source_id,
timestamp, author, related_entities) and a freshness signal so the agent's
reasoning can weigh a stale doc against a recent PR/incident.
"""

from __future__ import annotations

import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from models import Commit, Document, Incident, LogEntry, Message, PullRequest, Ticket, WikiPage


def _corpus_entry(
    source: str, source_id: str, timestamp, author: str | None, content: str, related_entities: list[str]
) -> dict:
    return {
        "source": source,
        "source_id": source_id,
        "timestamp": timestamp.isoformat() if timestamp else None,
        "author": author,
        "content": content,
        "related_entities": related_entities,
    }


def _collect_all(session) -> list[dict]:
    entries = []
    for m in session.query(Message).all():
        entries.append(
            _corpus_entry(
                "slack", m.message_id, m.timestamp, m.author_id, f"[{m.channel}] {m.content}", m.mentions
            )
        )
    for d in session.query(Document).all():
        entries.append(
            _corpus_entry(
                "drive", d.doc_id, d.updated_at, d.owner_id, f"{d.title}\n\n{d.content}", d.mentions
            )
        )
    for t in session.query(Ticket).all():
        comment_text = " ".join(c.get("text", "") for c in t.comments)
        entries.append(
            _corpus_entry(
                "ticket",
                t.ticket_id,
                None,
                t.assignee_id,
                f"{t.title}\n{t.description}\n{comment_text}",
                [t.related_incident_id, t.related_pr_id],
            )
        )
    for i in session.query(Incident).all():
        entries.append(
            _corpus_entry(
                "incident",
                i.incident_id,
                i.started_at,
                None,
                f"{i.title}\n{i.symptoms}",
                [i.service, i.related_deployment_id],
            )
        )
    for p in session.query(PullRequest).all():
        entries.append(
            _corpus_entry(
                "pull_request",
                p.pr_id,
                p.merged_at,
                p.author_id,
                f"{p.title}\n{p.description}",
                [p.repo_id, p.commit_id],
            )
        )
    for c in session.query(Commit).all():
        entries.append(_corpus_entry("commit", c.commit_id, c.timestamp, c.author_id, c.message, [c.repo_id]))
    for w in session.query(WikiPage).all():
        entries.append(
            _corpus_entry(
                "wiki",
                w.page_id,
                w.updated_at,
                w.owner_id,
                f"[{w.space}] {w.title}\n\n{w.content}",
                w.mentions,
            )
        )
    for log_row in session.query(LogEntry).all():
        entries.append(
            _corpus_entry(
                "log",
                log_row.log_id,
                log_row.timestamp,
                None,
                f"{log_row.severity} {log_row.service}: {log_row.message}",
                [log_row.service, log_row.deployment_id, log_row.trace_id],
            )
        )
    return [e for e in entries if e["content"].strip()]


def search_all(session, query: str, top_k: int = 8, sources: list[str] | None = None) -> list[dict]:
    """Hybrid retrieval: keyword filter (any query token appears) unioned with
    TF-IDF cosine similarity ranking, deduped, sorted by relevance."""
    entries = _collect_all(session)
    if sources:
        entries = [e for e in entries if e["source"] in sources]
    if not entries:
        return []

    corpus = [e["content"] for e in entries] + [query]
    vec = TfidfVectorizer(stop_words="english", max_features=4000)
    try:
        tfidf = vec.fit_transform(corpus)
        sims = cosine_similarity(tfidf[-1], tfidf[:-1]).flatten()
    except ValueError:
        sims = [0.0] * len(entries)

    query_tokens = set(re.findall(r"[a-zA-Z0-9_\-]+", query.lower()))
    ranked = []
    for entry, score in zip(entries, sims, strict=True):
        content_tokens = set(re.findall(r"[a-zA-Z0-9_\-]+", entry["content"].lower()))
        keyword_hits = len(query_tokens & content_tokens)
        combined = float(score) + 0.05 * keyword_hits
        if combined > 0:
            ranked.append((combined, entry))

    ranked.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, entry in ranked[:top_k]:
        entry = dict(entry)
        entry["relevance"] = round(score, 3)
        results.append(entry)
    return results


def search_by_entity_id(session, entity_id: str) -> list[dict]:
    """Direct lookup: find everything that mentions a specific entity id
    (e.g. 'PR-142', 'INC-464', 'DEP-45') regardless of TF-IDF relevance."""
    entries = _collect_all(session)
    results = []
    for e in entries:
        if entity_id in (e["related_entities"] or []) or entity_id in e["content"]:
            results.append(e)
    return results
