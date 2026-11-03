"""Shared response helpers."""

from urllib.parse import quote


def attachment(filename: str) -> str:
    """``Content-Disposition`` for downloading *filename*, which may not be ASCII: an
    ASCII fallback (``_`` for what it can't hold, which Windows accepts) and the UTF-8 name
    (RFC 6266)."""
    fallback = "".join(c if c.isascii() and c not in '"\\' else "_" for c in filename)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"
