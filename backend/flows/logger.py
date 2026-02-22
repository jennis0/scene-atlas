"""Logging helper for Prefect flows.

Provides a unified logger that uses the Prefect run logger (with flow/task run context)
when called inside a flow or task, and falls back to a standard Python logger outside
of a Prefect context (tests, CLI scripts, API routes that call flow helpers).

Usage — call at the TOP of each flow, task, or helper function (not at module level):

    def my_function():
        logger = get_logger(__name__)
        logger.info("This appears in the Prefect UI when called from a flow")
"""

import logging
from typing import Any


def get_logger(name: str | None = None) -> Any:
    """Return the Prefect run logger inside a flow/task, or a standard Python logger outside.

    ``get_run_logger()`` raises ``MissingContextError`` when called outside a Prefect
    flow or task run.  We catch that (and any other import/context error) and fall back
    to a standard ``logging.Logger`` so this helper is safe to call from anywhere.

    Args:
        name: Logger name used for the fallback standard logger (typically ``__name__``).
              Ignored when the Prefect run logger is returned (it carries run context).
    """
    try:
        from prefect import get_run_logger

        return get_run_logger()
    except Exception:
        return logging.getLogger(name or __name__)
