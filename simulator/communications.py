"""
Complete AI — organizational communications, documents, tickets, incidents,
deployments, and logs. All generated from the real RepoBuildResult objects
so every id (PR-xxx, DEP-xxx, INC-xxx, commit sha) referenced in a Slack
message or doc actually corresponds to a real row elsewhere.
"""

from __future__ import annotations

import datetime as dt
import random
import uuid

PEOPLE = [
    {"person_id": "eng-1", "name": "Priya Nair", "role": "Senior Engineer", "team": "checkout"},
    {"person_id": "eng-2", "name": "Marcus Webb", "role": "Engineer", "team": "checkout"},
    {"person_id": "eng-3", "name": "Sofia Chen", "role": "Staff Engineer", "team": "payments-platform"},
    {"person_id": "eng-4", "name": "Daniel Osei", "role": "Engineer", "team": "notifications"},
    {"person_id": "eng-5", "name": "Renee Ito", "role": "SRE", "team": "platform"},
    {"person_id": "eng-6", "name": "Karan Mehta", "role": "Engineering Manager", "team": "checkout"},
]


def _new_id(rng: random.Random, prefix: str) -> str:
    return f"{prefix}-{''.join(rng.choices('0123456789abcdef', k=8))}"


def build_wiki_pages(rng: random.Random, repos: list, base_time: dt.datetime) -> list[dict]:
    pages = []
    pages.append(
        {
            "page_id": "WIKI-eng-standards",
            "title": "Engineering Standards",
            "space": "Engineering",
            "owner_id": "eng-6",
            "updated_at": base_time - dt.timedelta(days=120),
            "content": (
                "# Engineering Standards\n\n"
                "- Python formatting: **Black**, default settings.\n"
                "- Linting: **Ruff**, default rule set, must pass with zero errors before merge.\n"
                "- All bug-fix PRs must include a regression test that fails before the fix and "
                "passes after it.\n"
                "- Config constants (timeouts, limits, thresholds) must reference the owning "
                "service's runbook for their supported range, not be set from a code comment alone.\n"
                "- PR descriptions must link the ticket and, where applicable, the incident they "
                "resolve.\n"
            ),
            "mentions": [],
        }
    )
    checkout_repo = next((r for r in repos if r.repo_id == "checkout-service"), None)
    if checkout_repo:
        pages.append(
            {
                "page_id": "WIKI-oncall-checkout",
                "title": "checkout-service On-call Notes",
                "space": "Onboarding",
                "owner_id": "eng-1",
                "updated_at": base_time - dt.timedelta(days=15),
                "content": (
                    "# checkout-service On-call Notes\n\n"
                    "New on-call engineers: the most common page here is a gateway timeout spike. "
                    "Before touching anything, check whether GATEWAY_TIMEOUT_MS in "
                    "checkout_service/config.py still matches the range in the runbook — it's been "
                    "temporarily changed during migrations before and occasionally the revert gets "
                    "missed.\n"
                ),
                "mentions": ["checkout-service"],
            }
        )
    return pages


def build_deployments(rng: random.Random, repos: list, base_time: dt.datetime) -> list[dict]:
    deployments = []
    for repo in repos:
        if not repo.commits:
            continue
        # one deployment per commit, timestamped shortly after the commit
        for c in repo.commits[-2:]:  # last couple of commits deployed
            dep_id = f"DEP-{rng.randint(10,99)}"
            deployments.append(
                {
                    "deployment_id": dep_id,
                    "repo_id": repo.repo_id,
                    "pr_ids": [],  # filled in by build_pull_requests
                    "deployed_at": c["timestamp"] + dt.timedelta(hours=rng.randint(1, 6)),
                    "status": "succeeded",
                    "commit_id": c["commit_id"],
                }
            )
    return deployments


def build_pull_requests(rng: random.Random, repos: list, deployments: list[dict]) -> list[dict]:
    prs = []
    dep_by_commit = {d["commit_id"]: d for d in deployments}
    pr_counter = [100 + rng.randint(0, 50)]

    for repo in repos:
        for c in repo.commits:
            pr_counter[0] += rng.randint(1, 4)
            pr_id = f"PR-{pr_counter[0]}"
            desc = c["message"]
            if repo.bug and c["commit_id"] == repo.bug.get("regression_commit"):
                desc = (
                    f"Temporarily lowers GATEWAY_TIMEOUT_MS to {repo.bug['bad_value']}ms while the "
                    f"gateway migration is in progress. Gateway team expects migration to complete "
                    f"within a few days; will revert once confirmed. Should have minimal impact since "
                    f"most requests complete well under this."
                )
            elif repo.repo_id == "payment-router" and "fallback" in c["message"].lower():
                desc = (
                    "Adds a same-request fallback to a secondary gateway when the primary declines. "
                    "Peak-traffic decline rates on the primary gateway have been running 3-4x baseline "
                    "for Visa/Mastercard during the last two incidents (see #payments thread). This "
                    "recovers most of those transactions without a customer-visible retry."
                )
            prs.append(
                {
                    "pr_id": pr_id,
                    "repo_id": repo.repo_id,
                    "title": c["message"],
                    "description": desc,
                    "author_id": None,
                    "commit_id": c["commit_id"],
                    "merged_at": c["timestamp"],
                    "status": "merged",
                }
            )
            dep = dep_by_commit.get(c["commit_id"])
            if dep is not None:
                dep.setdefault("pr_ids", []).append(pr_id)
    return prs


def build_incidents(
    rng: random.Random, repos: list, deployments: list[dict], base_time: dt.datetime
) -> list[dict]:
    incidents = []
    checkout_repo = next((r for r in repos if r.repo_id == "checkout-service"), None)
    if checkout_repo and checkout_repo.bug:
        dep = next(
            (
                d
                for d in deployments
                if d["repo_id"] == "checkout-service"
                and d["commit_id"] == checkout_repo.bug["regression_commit"]
            ),
            None,
        )
        started = (dep["deployed_at"] if dep else base_time - dt.timedelta(days=6)) + dt.timedelta(
            hours=rng.randint(2, 20)
        )
        inc_id = f"INC-{rng.randint(400,499)}"
        incidents.append(
            {
                "incident_id": inc_id,
                "service": "checkout-service",
                "title": "Checkout p95 latency and failure rate increased",
                "symptoms": (
                    "Checkout success rate dropped from ~99.6% to ~94% starting a few hours after the "
                    "last checkout-service release. Customer support tickets mention 'payment timed out, "
                    "please try again'. p95 checkout latency dashboard shows elevated gateway timeout errors."
                ),
                "started_at": started,
                "related_deployment_id": dep["deployment_id"] if dep else None,
                "status": "investigating",
                "timeline": [
                    {
                        "time": started.isoformat(),
                        "event": "Alert fired: checkout error rate above threshold",
                    },
                    {
                        "time": (started + dt.timedelta(minutes=12)).isoformat(),
                        "event": "On-call confirms elevated GatewayTimeoutError rate in logs",
                    },
                ],
            }
        )

    notif_repo = next((r for r in repos if r.repo_id == "notification-service"), None)
    if notif_repo and notif_repo.bug:
        started = base_time - dt.timedelta(days=rng.randint(2, 5))
        inc_id = f"INC-{rng.randint(500,599)}"
        incidents.append(
            {
                "incident_id": inc_id,
                "service": "notification-service",
                "title": "Customers reporting duplicate order confirmation emails",
                "symptoms": (
                    "Multiple support tickets from customers who received 2 confirmation emails for the "
                    "same order. Appears correlated with order-service retry behavior during brief "
                    "notification-service latency spikes."
                ),
                "started_at": started,
                "related_deployment_id": None,
                "status": "open",
                "timeline": [
                    {"time": started.isoformat(), "event": "First customer report via support"},
                ],
            }
        )
    return incidents


def build_logs(rng: random.Random, repos: list, incidents: list[dict]) -> list[dict]:
    logs = []
    checkout_inc = next((i for i in incidents if i["service"] == "checkout-service"), None)
    if checkout_inc:
        start = checkout_inc["started_at"]
        for i in range(60):
            t = start + dt.timedelta(seconds=i * 15)
            r = rng.random()
            if r < 0.35:
                latency = rng.uniform(950, 1800)
                logs.append(
                    {
                        "log_id": f"LOG-{uuid.uuid4().hex[:8]}",
                        "timestamp": t,
                        "service": "checkout-service",
                        "severity": "ERROR",
                        "request_id": f"req-{uuid.uuid4().hex[:6]}",
                        "trace_id": f"trace-{uuid.uuid4().hex[:6]}",
                        "deployment_id": checkout_inc["related_deployment_id"],
                        "message": f"GatewayTimeoutError: gateway call exceeded timeout ({latency:.0f}ms observed)",
                        "latency_ms": latency,
                        "status_code": 504,
                    }
                )
            else:
                latency = rng.uniform(150, 700)
                logs.append(
                    {
                        "log_id": f"LOG-{uuid.uuid4().hex[:8]}",
                        "timestamp": t,
                        "service": "checkout-service",
                        "severity": "INFO",
                        "request_id": f"req-{uuid.uuid4().hex[:6]}",
                        "trace_id": f"trace-{uuid.uuid4().hex[:6]}",
                        "deployment_id": checkout_inc["related_deployment_id"],
                        "message": "checkout authorized",
                        "latency_ms": latency,
                        "status_code": 200,
                    }
                )
    return logs


def build_tickets(rng: random.Random, incidents: list[dict], prs: list[dict]) -> list[dict]:
    tickets = []
    checkout_inc = next((i for i in incidents if i["service"] == "checkout-service"), None)
    if checkout_inc:
        tickets.append(
            {
                "ticket_id": f"TCK-{rng.randint(1000,1999)}",
                "title": "Investigate checkout latency spike",
                "description": "Support escalated multiple reports of failed checkouts. See INC thread.",
                "priority": "P1",
                "status": "in_progress",
                "assignee_id": "eng-1",
                "related_incident_id": checkout_inc["incident_id"],
                "related_pr_id": None,
                "comments": [{"author": "eng-6", "text": "Prioritizing — this is affecting conversion."}],
            }
        )
    notif_inc = next((i for i in incidents if i["service"] == "notification-service"), None)
    if notif_inc:
        tickets.append(
            {
                "ticket_id": f"TCK-{rng.randint(2000,2999)}",
                "title": "Customers reporting duplicate confirmation emails after retries",
                "description": "See incident. Need root cause and fix in notification-service.",
                "priority": "P2",
                "status": "open",
                "assignee_id": "eng-4",
                "related_incident_id": notif_inc["incident_id"],
                "related_pr_id": None,
                "comments": [],
            }
        )
    tickets.append(
        {
            "ticket_id": f"TCK-{rng.randint(3000,3999)}",
            "title": "Standardize error response schema across all services",
            "description": (
                "checkout-service, payment-router, and notification-service each return a "
                "differently-shaped error dict. See DOC-unified-error-schema for the target "
                "contract. Needs a coordinated change across all three repos."
            ),
            "priority": "P2",
            "status": "open",
            "assignee_id": "eng-6",
            "related_incident_id": None,
            "related_pr_id": None,
            "comments": [
                {
                    "author": "eng-6",
                    "text": "This blocks the generic error-handling "
                    "dashboard work — needs all three services.",
                }
            ],
        }
    )
    return tickets


def build_sim_events(
    rng: random.Random,
    repos: list,
    incidents: list[dict],
    tickets: list[dict],
    deployments: list[dict],
    base_time: dt.datetime,
) -> list[dict]:
    """
    The 'zero user prompt' entry doors: events that appear on their own,
    exactly like every other seeded entity, rather than being typed by a
    human. Dispatching one runs the same CompleteAgent.run() loop as any
    other task — the only difference is where the objective came from.
    """
    events = []
    checkout_inc = next((i for i in incidents if i["service"] == "checkout-service"), None)
    if checkout_inc:
        dep = next(
            (d for d in deployments if d["deployment_id"] == checkout_inc.get("related_deployment_id")), None
        )
        events.append(
            {
                "event_id": f"EVT-{uuid.uuid4().hex[:8]}",
                "source": "github_ci",
                "title": f"CI failing on checkout-service after {dep['deployment_id'] if dep else 'the latest deploy'}",
                "detail": f"2 tests failing on branch master following commit "
                f"{dep.get('commit_id', 'unknown') if dep else 'unknown'}. "
                f"test_reproduces_latency_regression and test_timeout_within_legacy_client_bounds "
                f"both red.",
                "derived_objective": "CI is failing on checkout-service after the last merge to master. "
                "Investigate the failing tests and fix them.",
                "related_repo_id": "checkout-service",
                "related_entity_id": checkout_inc["incident_id"],
                "created_at": base_time - dt.timedelta(hours=2),
            }
        )

    notif_ticket = next((t for t in tickets if "duplicate" in t["title"].lower()), None)
    if notif_ticket:
        events.append(
            {
                "event_id": f"EVT-{uuid.uuid4().hex[:8]}",
                "source": "ticket_assigned",
                "title": f"{notif_ticket['ticket_id']} auto-assigned to Complete AI",
                "detail": f"\u201c{notif_ticket['title']}\u201d was routed to Complete AI by the triage bot "
                f"based on the notification-service label.",
                "derived_objective": notif_ticket["ticket_id"],
                "related_repo_id": "notification-service",
                "related_entity_id": notif_ticket["ticket_id"],
                "created_at": base_time - dt.timedelta(hours=1),
            }
        )

    return events


def build_messages(
    rng: random.Random, repos: list, incidents: list[dict], prs: list[dict], base_time: dt.datetime
) -> list[dict]:
    messages = []

    checkout_repo = next((r for r in repos if r.repo_id == "checkout-service"), None)
    checkout_inc = next((i for i in incidents if i["service"] == "checkout-service"), None)
    if checkout_repo and checkout_repo.bug:
        reg_pr = next(
            (
                p
                for p in prs
                if p["repo_id"] == "checkout-service"
                and p["commit_id"] == checkout_repo.bug["regression_commit"]
            ),
            None,
        )
        pr_ref = reg_pr["pr_id"] if reg_pr else "PR-unknown"
        t0 = checkout_repo.commits[-1]["timestamp"]
        thread_id = f"thread-{uuid.uuid4().hex[:6]}"
        messages += [
            {
                "message_id": f"MSG-{uuid.uuid4().hex[:8]}",
                "channel": "#checkout",
                "thread_id": thread_id,
                "author_id": "eng-2",
                "timestamp": t0,
                "content": f"Merging {pr_ref} — temporarily lowering the gateway timeout while the gateway "
                f"team finishes their migration. Should be safe, most calls finish way under this.",
                "mentions": [pr_ref, "checkout-service"],
            },
            {
                "message_id": f"MSG-{uuid.uuid4().hex[:8]}",
                "channel": "#checkout",
                "thread_id": thread_id,
                "author_id": "eng-6",
                "timestamp": t0 + dt.timedelta(minutes=4),
                "content": "Sounds good, just make sure we revert once migration's done — don't want this "
                "lingering.",
                "mentions": [pr_ref],
            },
        ]
        if checkout_inc:
            t1 = checkout_inc["started_at"] + dt.timedelta(minutes=20)
            inc_thread = f"thread-{uuid.uuid4().hex[:6]}"
            messages += [
                {
                    "message_id": f"MSG-{uuid.uuid4().hex[:8]}",
                    "channel": "#incidents",
                    "thread_id": inc_thread,
                    "author_id": "eng-5",
                    "timestamp": t1,
                    "content": f"Paging on {checkout_inc['incident_id']} — checkout error rate is up, looks "
                    f"like gateway timeouts. Correlates with the last checkout-service deploy.",
                    "mentions": [checkout_inc["incident_id"], "checkout-service"],
                },
                {
                    "message_id": f"MSG-{uuid.uuid4().hex[:8]}",
                    "channel": "#incidents",
                    "thread_id": inc_thread,
                    "author_id": "eng-1",
                    "timestamp": t1 + dt.timedelta(minutes=6),
                    "content": f"That deploy included {pr_ref}, which lowered the gateway timeout. Gateway "
                    f"p95 has actually been running closer to 900ms lately, so that tracks.",
                    "mentions": [pr_ref],
                },
            ]

    payment_repo = next((r for r in repos if r.repo_id == "payment-router"), None)
    if payment_repo:
        fb_pr = next(
            (p for p in prs if p["repo_id"] == "payment-router" and "fallback" in p["title"].lower()), None
        )
        pr_ref = fb_pr["pr_id"] if fb_pr else "PR-unknown"
        t = payment_repo.commits[-1]["timestamp"]
        messages.append(
            {
                "message_id": f"MSG-{uuid.uuid4().hex[:8]}",
                "channel": "#payments",
                "thread_id": f"thread-{uuid.uuid4().hex[:6]}",
                "author_id": "eng-3",
                "timestamp": t,
                "content": f"Shipped {pr_ref}: payment-router now falls back to the secondary gateway "
                f"same-request when the primary declines. Primary's decline rate for Visa/MC "
                f"has been 3-4x baseline during peak traffic for the last two incidents — this "
                f"should recover most of that without a customer-visible retry.",
                "mentions": [pr_ref, "payment-router"],
            }
        )

    notif_repo = next((r for r in repos if r.repo_id == "notification-service"), None)
    notif_inc = next((i for i in incidents if i["service"] == "notification-service"), None)
    if notif_repo and notif_inc:
        t = notif_inc["started_at"] + dt.timedelta(hours=3)
        messages.append(
            {
                "message_id": f"MSG-{uuid.uuid4().hex[:8]}",
                "channel": "#backend",
                "thread_id": f"thread-{uuid.uuid4().hex[:6]}",
                "author_id": "eng-4",
                "timestamp": t,
                "content": f"Couple reports of duplicate confirmation emails today. Order-service does retry "
                f"notification-service on timeout — wondering if we're missing an idempotency "
                f"check on the send path. Filed {notif_inc['incident_id']}.",
                "mentions": [notif_inc["incident_id"], "notification-service"],
            }
        )

    return messages


def build_documents(rng: random.Random, repos: list, base_time: dt.datetime) -> list[dict]:
    docs = []
    all_repo_ids = [r.repo_id for r in repos]
    docs.append(
        {
            "doc_id": "DOC-unified-error-schema",
            "title": "Unified Error Schema",
            "doc_type": "architecture",
            "owner_id": "eng-6",
            "updated_at": base_time - dt.timedelta(days=30),
            "content": (
                "# Unified Error Schema\n\n"
                "Every internal service must return the same shape on a handled failure:\n\n"
                '```json\n{"error_code": "<UPPER_SNAKE_CASE>", "message": "<human readable>"}\n```\n\n'
                "## Why\n\nBefore this standard, checkout-service, payment-router, and "
                "notification-service each returned a differently-shaped error dict "
                "(`error`, `failure_reason`, `reason`). Any client or dashboard trying to "
                "handle failures generically had to special-case every service.\n\n"
                "## Rollout\n\nAll services listed below are expected to conform:\n\n"
                + "\n".join(f"- {rid}" for rid in all_repo_ids)
                + "\n\n"
                "Each service's `errors.py` module owns this conversion — see "
                "`to_error_response()` in each repository.\n"
            ),
            "mentions": all_repo_ids,
        }
    )
    docs.append(
        {
            "doc_id": "DOC-checkout-runbook",
            "title": "checkout-service Runbook",
            "doc_type": "runbook",
            "owner_id": "eng-1",
            "updated_at": base_time - dt.timedelta(days=200),
            "content": (
                "# checkout-service Runbook\n\n"
                "## Gateway timeout\n\n"
                "`GATEWAY_TIMEOUT_MS` (in `checkout_service/config.py`) controls how long we wait for the "
                "external payment gateway before treating a request as failed.\n\n"
                "Recommended range: **between 900ms and 1500ms**.\n\n"
                "- Below 900ms: gateway p95 latency alone (observed 850-950ms under normal load) will "
                "trip the timeout for a meaningful fraction of legitimate requests.\n"
                "- Above 1500ms: the legacy mobile checkout client hard-closes its socket at 1500ms, so "
                "values above that surface as client-side connection resets instead of clean gateway "
                "timeouts, which is worse for observability and customer experience.\n\n"
                "## On-call\n\nIf checkout error rate alerts fire, check recent deployments to "
                "checkout-service first, then compare GATEWAY_TIMEOUT_MS against this range.\n"
            ),
            "mentions": ["checkout-service"],
        }
    )
    docs.append(
        {
            "doc_id": "DOC-payment-router-fallback",
            "title": "Payment Router Fallback Strategy",
            "doc_type": "architecture",
            "owner_id": "eng-3",
            "updated_at": base_time - dt.timedelta(days=55),
            "content": (
                "# Payment Router Fallback Strategy\n\n"
                "payment-router routes each charge to a primary gateway. On a primary decline, it "
                "immediately retries the same request against a secondary gateway before returning to "
                "the caller (see `payment_router/router.py`, PR-118).\n\n"
                "## Why\n\nDuring the two most recent peak-traffic incidents, the primary gateway's "
                "decline rate for Visa/Mastercard ran 3-4x its normal baseline. Falling back within the "
                "same request recovers most of those transactions without a customer-visible retry, which "
                "materially improved checkout conversion during the following peak window.\n\n"
                "## Tradeoffs\n\nThe fallback gateway has a slightly higher per-transaction fee, so this "
                "is deliberately scoped to same-request fallback on decline only, not a general dual-write.\n"
            ),
            "mentions": ["payment-router", "PR-118"],
        }
    )
    docs.append(
        {
            "doc_id": "DOC-notification-onboarding",
            "title": "notification-service Onboarding",
            "doc_type": "onboarding",
            "owner_id": "eng-4",
            "updated_at": base_time - dt.timedelta(days=300),
            "content": (
                "# notification-service Onboarding\n\n"
                "Sends transactional emails (order confirmation, shipping updates, etc). Called by "
                "order-service. Note: order-service retries on any non-2xx or timeout response, so "
                "every send path here should be idempotent per order_id — this is a known gap, tracked "
                "informally but not yet fixed.\n"
            ),
            "mentions": ["notification-service"],
        }
    )
    return docs
