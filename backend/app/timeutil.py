"""Timestamps as the database stores them."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Now in UTC, naive: every timestamp column holds naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)
