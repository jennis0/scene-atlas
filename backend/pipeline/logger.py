"""Logging helper for pipeline modules.

Provides a unified ``get_logger()`` function that returns a standard
Python logger.  All call-sites use ``get_logger(__name__)`` so no
changes are needed anywhere else.
"""

import logging
from typing import Any


def get_logger(name: str | None = None) -> Any:
    """Return a standard Python logger."""
    return logging.getLogger(name or __name__)
