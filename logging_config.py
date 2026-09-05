"""
Complete AI — structured logging.

Anywhere the codebase catches a broad exception to keep a task or an
optional feature from crashing (an LLM call falling back to the
deterministic answer, a best-effort subprocess probe), the exception is
logged here rather than silently discarded — a broad `except Exception`
that swallows the error with no trace is exactly the kind of thing that
turns into an unreproducible bug report in production. Narrow excepts are
still used wherever the failure mode is actually known ahead of time.
"""

from __future__ import annotations

import logging
import os
import sys

_LEVEL = os.environ.get("COMPLETE_AI_LOG_LEVEL", "INFO").upper()

_logger = logging.getLogger("complete_ai")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    )
    _logger.addHandler(_handler)
    _logger.setLevel(_LEVEL)
    _logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    return _logger.getChild(name) if name else _logger
