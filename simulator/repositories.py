"""
Complete AI — repository builder.

Creates real, small, runnable Python repositories on disk, each with a real
git history (via GitPython), real pytest test suites, and — for two of the
three repos — a real bug seeded into the actual source code (not just
described in metadata). The exact bad values are seed-randomized, so which
repo misbehaves and by how much varies run to run while remaining
deterministically reproducible for a given seed.
"""

from __future__ import annotations

import datetime as dt
import os
import random
import shutil
import subprocess
from dataclasses import dataclass, field

from git import Repo


@dataclass
class RepoBuildResult:
    repo_id: str
    name: str
    description: str
    path: str
    commits: list[dict] = field(default_factory=list)  # {commit_id, message, timestamp, files_changed}
    bug: dict | None = None  # {bug_type, file_path, description, bad_value, good_range}


def _add_error_schema_module(path: str, package: str, current_shape_code: str):
    """
    Adds a real cross-service inconsistency used by the multi-repo demo: an
    `errors.py` module whose to_error_response() shape differs per service,
    plus a real test asserting the shared contract from the "Unified Error
    Schema" architecture doc — which genuinely fails until all three
    services are normalized to it. This is baked into each repo's initial
    commit (not a later regression), since it represents pre-existing
    cross-service drift rather than a specific incident.
    """
    _write(
        f"{path}/{package}/errors.py",
        f"""\
\"\"\"
Error response construction for this service.

See docs/architecture/unified-error-schema.md for the company-wide contract
every service is expected to return on failure: {{"error_code": str,
"message": str}}. This service does not conform yet.
\"\"\"


def to_error_response(reason: str) -> dict:
{current_shape_code}
""",
    )
    _write(
        f"{path}/tests/test_error_schema.py",
        f"""\
from {package}.errors import to_error_response


def test_error_schema_matches_unified_contract():
    \"\"\"Every service must return {{"error_code": str, "message": str}} on
    failure — see docs/architecture/unified-error-schema.md.\"\"\"
    result = to_error_response("something_failed")
    assert set(result.keys()) == {{"error_code", "message"}}, (
        f"error response shape {{sorted(result.keys())}} does not match the "
        f"unified contract {{{{'error_code', 'message'}}}}"
    )
""",
    )


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _normalize_formatting(repo_path: str):
    """Runs ruff --fix and black on a freshly-written repo before its first
    commit, so the baseline state is genuinely lint/format-clean — the same
    real tools Complete AI itself runs later only need to flag something if
    the agent's own edit introduces a real issue, not pre-existing noise."""
    subprocess.run(
        ["python3", "-m", "ruff", "check", "--fix", "--quiet", "."],
        cwd=repo_path,
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["python3", "-m", "black", "--quiet", "."], cwd=repo_path, capture_output=True, check=False
    )


def _init_repo_with_local_identity(path: str) -> Repo:
    """Repo.init plus a LOCAL (not global) git identity, configured
    immediately, so every commit made during generation — and every commit
    later made against a sandboxed copy of this repo — works regardless of
    whether the host machine has any global git config at all. This is the
    single source of truth other init call sites in this file reuse."""
    repo = Repo.init(path)
    with repo.config_writer(config_level="repository") as cw:
        cw.set_value("user", "name", "Complete AI Simulator")
        cw.set_value("user", "email", "simulator@complete.ai")
    return repo


def _commit(repo: Repo, message: str, author_name: str, when: dt.datetime) -> str:
    # NOTE: repo.index.add(["."]) does NOT behave like the real `git add .`
    # CLI (it doesn't reliably exclude .git or recurse correctly) — using
    # the actual git command via repo.git.add(A=True) avoids a real bug
    # this caused: the initial commit accidentally tracking .git's own
    # internal files while leaving the real source untracked, which made
    # every later `git diff` show garbage instead of the actual code change.
    repo.git.add(A=True)
    author_date = when.strftime("%Y-%m-%dT%H:%M:%S")
    commit = repo.index.commit(
        message,
        author_date=author_date,
        commit_date=author_date,
        author=None,
    )
    return commit.hexsha[:8]


# ---------------------------------------------------------------------------
# checkout-service — signature bug: gateway timeout regression
# ---------------------------------------------------------------------------


def build_checkout_service(root: str, rng: random.Random, base_time: dt.datetime) -> RepoBuildResult:
    path = os.path.join(root, "checkout-service")
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)
    repo = _init_repo_with_local_identity(path)

    good_value = 1200  # the value the runbook recommends and that satisfies both tests
    bad_value = rng.choice([200, 250, 300, 350, 400])

    _write(f"{path}/checkout_service/__init__.py", "")
    _write(
        f"{path}/checkout_service/config.py",
        f"""\
# Gateway timeout configuration.
#
# See docs/runbooks/checkout-runbook.md for the supported range. This value
# is read by gateway_client.call_gateway() on every checkout attempt.
GATEWAY_TIMEOUT_MS = {good_value}
""",
    )
    _write(
        f"{path}/checkout_service/gateway_client.py",
        """\
from checkout_service.config import GATEWAY_TIMEOUT_MS


class GatewayTimeoutError(Exception):
    pass


def call_gateway(simulated_latency_ms: float) -> dict:
    \"\"\"Simulates a call to the external payment gateway. Raises
    GatewayTimeoutError if the (simulated) round-trip latency exceeds the
    configured timeout.\"\"\"
    if simulated_latency_ms > GATEWAY_TIMEOUT_MS:
        raise GatewayTimeoutError(
            f"gateway call exceeded timeout: {simulated_latency_ms:.0f}ms > {GATEWAY_TIMEOUT_MS}ms"
        )
    return {"status": "authorized", "latency_ms": simulated_latency_ms}
""",
    )
    _write(
        f"{path}/checkout_service/checkout.py",
        """\
from checkout_service.gateway_client import call_gateway, GatewayTimeoutError


def process_checkout(order_id: str, simulated_latency_ms: float) -> dict:
    try:
        result = call_gateway(simulated_latency_ms)
        return {"order_id": order_id, "status": "success", "latency_ms": result["latency_ms"]}
    except GatewayTimeoutError as e:
        return {"order_id": order_id, "status": "failed", "reason": str(e)}
""",
    )
    _write(f"{path}/tests/__init__.py", "")
    _write(
        f"{path}/tests/test_checkout.py",
        """\
import random
from checkout_service.checkout import process_checkout
from checkout_service.config import GATEWAY_TIMEOUT_MS

# Realistic gateway latency distribution observed in production logs around
# the incident window: p50 ~450ms, p95 ~850-950ms, occasional spikes to
# ~1400ms. This mirrors log_entries generated for the same incident.
def _realistic_latencies(n: int, seed: int = 1234) -> list[float]:
    rng = random.Random(seed)
    latencies = []
    for _ in range(n):
        r = rng.random()
        if r < 0.50:
            latencies.append(rng.uniform(150, 450))
        elif r < 0.95:
            latencies.append(rng.uniform(450, 950))
        else:
            latencies.append(rng.uniform(950, 1400))
    return latencies


def test_reproduces_latency_regression():
    \"\"\"Reproduction of INC latency regression: under realistic gateway
    latency, checkout success rate must stay at or above 98%.\"\"\"
    latencies = _realistic_latencies(300)
    results = [process_checkout(f"ORD-{i}", lat) for i, lat in enumerate(latencies)]
    success_rate = sum(1 for r in results if r["status"] == "success") / len(results)
    assert success_rate >= 0.98, (
        f"checkout success rate {success_rate:.3f} is below the 0.98 SLA under realistic "
        f"gateway latency with GATEWAY_TIMEOUT_MS={GATEWAY_TIMEOUT_MS}"
    )


def test_timeout_within_legacy_client_bounds():
    \"\"\"The legacy mobile checkout client hard-closes its socket at 1500ms,
    so any configured timeout above that is incompatible and will surface as
    client-side connection resets rather than clean gateway timeouts.\"\"\"
    assert 900 <= GATEWAY_TIMEOUT_MS <= 1500, (
        f"GATEWAY_TIMEOUT_MS must be between 900 and 1500 for legacy client "
        f"compatibility (got {GATEWAY_TIMEOUT_MS})"
    )
""",
    )
    ts0 = base_time - dt.timedelta(days=40)
    _add_error_schema_module(path, "checkout_service", '    return {"error": reason}')
    _normalize_formatting(path)
    _commit(repo, "Initial checkout-service scaffold", "eng-1", ts0)
    commits = [
        {
            "commit_id": repo.head.commit.hexsha[:8],
            "message": "Initial checkout-service scaffold",
            "timestamp": ts0,
            "files_changed": ["checkout_service/", "tests/"],
        }
    ]

    # The regression commit: lower the timeout ("temporarily, until gateway migration finishes")
    _write(
        f"{path}/checkout_service/config.py",
        f"""\
# Gateway timeout configuration.
#
# See docs/runbooks/checkout-runbook.md for the supported range. This value
# is read by gateway_client.call_gateway() on every checkout attempt.
#
# TEMP: lowered while the gateway migration is in flight — see #checkout
# discussion. Revert once migration completes.
GATEWAY_TIMEOUT_MS = {bad_value}
""",
    )
    ts1 = base_time - dt.timedelta(days=7)
    regression_sha = _commit(repo, "Lower gateway timeout during migration window", "eng-2", ts1)
    commits.append(
        {
            "commit_id": regression_sha,
            "message": "Lower gateway timeout during migration window",
            "timestamp": ts1,
            "files_changed": ["checkout_service/config.py"],
        }
    )

    return RepoBuildResult(
        repo_id="checkout-service",
        name="checkout-service",
        description="Handles checkout and payment authorization against the external gateway.",
        path=path,
        commits=commits,
        bug={
            "bug_type": "timeout_regression",
            "file_path": "checkout_service/config.py",
            "description": f"GATEWAY_TIMEOUT_MS lowered to {bad_value}ms, below the realistic gateway "
            f"p95 latency, causing elevated checkout failures.",
            "bad_value": bad_value,
            "good_value": good_value,
            "regression_commit": regression_sha,
        },
    )


# ---------------------------------------------------------------------------
# payment-router — bug: off-by-one in the retry policy (also the pure-
# knowledge fallback-strategy demo target, which remains unaffected since
# that demo never runs this repo's tests)
# ---------------------------------------------------------------------------


def build_payment_router(root: str, rng: random.Random, base_time: dt.datetime) -> RepoBuildResult:
    path = os.path.join(root, "payment-router")
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)
    repo = _init_repo_with_local_identity(path)

    _write(
        f"{path}/payment_router/retry_policy.py",
        '''"""
Decides whether the router should retry a payment attempt against the
fallback gateway. See docs/architecture/payment-router-fallback.md -- the
router is configured to allow up to MAX_ATTEMPTS total attempts before
giving up and surfacing a hard decline to the caller.
"""

MAX_ATTEMPTS = 3


def should_retry(attempt_count: int, max_attempts: int = MAX_ATTEMPTS) -> bool:
    # BUG: off-by-one -- subtracts an extra 1, so the router gives up one
    # attempt earlier than max_attempts actually allows.
    return attempt_count < max_attempts - 1
''',
    )
    _write(f"{path}/payment_router/__init__.py", "")
    _write(
        f"{path}/payment_router/router.py",
        """\
\"\"\"
Routes a payment to a primary gateway, falling back to a secondary gateway
on failure. See docs/architecture/payment-router-fallback.md and PR-118 for
why this exists: the primary gateway has a materially higher decline rate
for certain card networks during peak traffic, and a same-request fallback
recovers a meaningful fraction of otherwise-lost transactions without
requiring the customer to retry.
\"\"\"


class GatewayError(Exception):
    pass


def route_payment(amount: float, card_network: str, primary_gateway, fallback_gateway) -> dict:
    try:
        return primary_gateway.charge(amount, card_network)
    except GatewayError:
        # Same-request fallback — see PR-118 for the incident that motivated this.
        return fallback_gateway.charge(amount, card_network)
""",
    )
    _write(f"{path}/tests/__init__.py", "")
    _write(
        f"{path}/tests/test_router.py",
        """\
from payment_router.router import route_payment, GatewayError


class _FailingGateway:
    def charge(self, amount, card_network):
        raise GatewayError("declined")


class _WorkingGateway:
    def charge(self, amount, card_network):
        return {"status": "success", "amount": amount}


def test_falls_back_on_primary_failure():
    result = route_payment(100.0, "visa", _FailingGateway(), _WorkingGateway())
    assert result["status"] == "success"
""",
    )
    _write(
        f"{path}/tests/test_retry_policy.py",
        '''"""
See docs/architecture/payment-router-fallback.md: the router is configured
for MAX_ATTEMPTS=3 total attempts before giving up on a payment.
"""

from payment_router.retry_policy import should_retry


def test_should_retry_allows_full_configured_attempt_budget():
    """With max_attempts=3, the router must attempt exactly 3 times total
    (attempt_count 0, 1, 2) before giving up -- should_retry must return
    True for attempt_count=2 so the 3rd and final attempt is still allowed
    to happen, not silently dropped one attempt early."""
    outcome = should_retry(2, max_attempts=3)
    assert outcome is True, (
        f"should_retry(2, max_attempts=3) returned {outcome} -- with "
        f"max_attempts=3, attempt_count=2 is still within the configured "
        f"budget and must be allowed to retry"
    )


def test_should_retry_stops_after_budget_exhausted():
    outcome = should_retry(3, max_attempts=3)
    assert outcome is False, (
        f"should_retry(3, max_attempts=3) returned {outcome} -- once "
        f"attempt_count reaches max_attempts, no further retry is allowed"
    )
''',
    )
    ts0 = base_time - dt.timedelta(days=90)
    _add_error_schema_module(path, "payment_router", '    return {"failure_reason": reason}')
    _normalize_formatting(path)
    _commit(repo, "Initial payment-router", "eng-3", ts0)
    commits = [
        {
            "commit_id": repo.head.commit.hexsha[:8],
            "message": "Initial payment-router",
            "timestamp": ts0,
            "files_changed": ["payment_router/", "tests/"],
        }
    ]

    ts1 = base_time - dt.timedelta(days=60)
    sha = _commit(repo, "Add same-request fallback gateway for peak-traffic declines", "eng-3", ts1)
    commits.append(
        {
            "commit_id": sha,
            "message": "Add same-request fallback gateway for peak-traffic declines",
            "timestamp": ts1,
            "files_changed": ["payment_router/router.py"],
        }
    )

    return RepoBuildResult(
        repo_id="payment-router",
        name="payment-router",
        description="Routes payments across gateways with same-request fallback.",
        path=path,
        commits=commits,
        bug={
            "bug_type": "retry_off_by_one",
            "file_path": "payment_router/retry_policy.py",
            "description": "should_retry() subtracts an extra 1 from max_attempts, so the router "
            "gives up one attempt earlier than the configured MAX_ATTEMPTS actually allows.",
            "bad_value": None,
            "good_value": None,
            "regression_commit": None,
        },
    )


# ---------------------------------------------------------------------------
# notification-service — bug: duplicate confirmation emails on retry
# ---------------------------------------------------------------------------


def build_notification_service(root: str, rng: random.Random, base_time: dt.datetime) -> RepoBuildResult:
    path = os.path.join(root, "notification-service")
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)
    repo = _init_repo_with_local_identity(path)

    _write(f"{path}/notification_service/__init__.py", "")
    _write(
        f"{path}/notification_service/sender.py",
        """\
\"\"\"
Sends order confirmation emails. The upstream order service retries this
call on transient network errors, so this module is expected to be called
more than once for the same order_id.
\"\"\"

_sent_log = []  # simulated outbox, for tests only


def reset_outbox():
    _sent_log.clear()


def send_confirmation_email(order_id: str, retry: bool = False) -> dict:
    # BUG: no idempotency check — every call sends an email, so retries after
    # a transient failure produce duplicate confirmation emails.
    _sent_log.append(order_id)
    return {"order_id": order_id, "sent": True, "retry": retry}


def outbox_count(order_id: str) -> int:
    return _sent_log.count(order_id)
""",
    )
    _write(f"{path}/tests/__init__.py", "")
    _write(
        f"{path}/tests/test_sender.py",
        """\
from notification_service.sender import send_confirmation_email, outbox_count, reset_outbox


def test_no_duplicate_emails_on_retry():
    reset_outbox()
    order_id = "ORD-RETRY-1"
    # Simulate the upstream retry behavior: the first attempt times out on
    # the caller's side (but actually succeeded server-side) and the caller
    # retries once with the same order_id.
    send_confirmation_email(order_id, retry=False)
    send_confirmation_email(order_id, retry=True)
    assert outbox_count(order_id) == 1, (
        f"expected exactly 1 confirmation email for {order_id}, "
        f"got {outbox_count(order_id)} (retry sent a duplicate)"
    )
""",
    )
    ts0 = base_time - dt.timedelta(days=120)
    _add_error_schema_module(path, "notification_service", '    return {"reason": reason}')
    _normalize_formatting(path)
    _commit(repo, "Initial notification-service", "eng-4", ts0)
    commits = [
        {
            "commit_id": repo.head.commit.hexsha[:8],
            "message": "Initial notification-service",
            "timestamp": ts0,
            "files_changed": ["notification_service/", "tests/"],
        }
    ]

    return RepoBuildResult(
        repo_id="notification-service",
        name="notification-service",
        description="Sends transactional emails for order lifecycle events.",
        path=path,
        commits=commits,
        bug={
            "bug_type": "duplicate_send_on_retry",
            "file_path": "notification_service/sender.py",
            "description": "send_confirmation_email has no idempotency check, so retries after a "
            "transient failure send duplicate confirmation emails.",
        },
    )


def build_all_repositories(
    workspace_root: str, rng: random.Random, base_time: dt.datetime
) -> list[RepoBuildResult]:
    os.makedirs(workspace_root, exist_ok=True)
    return [
        build_checkout_service(workspace_root, rng, base_time),
        build_payment_router(workspace_root, rng, base_time),
        build_notification_service(workspace_root, rng, base_time),
    ]
