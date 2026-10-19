"""Server-mode update check: is a newer Scene Atlas release out? (ADR-022)

A self-hosted server asks GitHub for the latest release shortly after startup and then
once a day, and keeps the answer in memory for ``GET /api/v1/system/updates``. Nothing
here runs in the desktop app (Electron has its own updater) or when the admin sets
``CHECK_FOR_UPDATES=false``: then no request is ever made.

Requests are never made on behalf of a user. Every user behind the proxy shares one
unauthenticated GitHub rate limit, so the API only ever returns the cached result.
"""

import asyncio
import contextlib
import http.client
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..models.schemas import UpdateCheckResponse, UpdateStatusKind

logger = logging.getLogger(__name__)

LATEST_RELEASE_API = "https://api.github.com/repos/jennis0/scene-atlas/releases/latest"
RELEASES_URL = "https://github.com/jennis0/scene-atlas/releases"

# A little after startup, so the check doesn't compete with it; then daily.
FIRST_CHECK_DELAY_SECONDS = 60.0
CHECK_INTERVAL_SECONDS = 24 * 60 * 60.0
REQUEST_TIMEOUT_SECONDS = 10.0
# A release's JSON is a few KB plus its notes; anything far larger isn't one.
MAX_RESPONSE_BYTES = 1024 * 1024

# "1.2.3", "1.2.3-beta.1" (semver) or "1.2.3b1" / "1.2.3rc1" (PEP 440). Anything else,
# such as a dev build's "1.2.3.dev4+g1a2b3c", can't be compared with a release.
_RELEASE = re.compile(r"(\d{1,6})\.(\d{1,6})\.(\d{1,6})")
_SEMVER_PRERELEASE = re.compile(r"-[0-9A-Za-z.-]{1,64}")
_PEP440_PRERELEASE = re.compile(r"(?:a|b|rc)\d{1,6}")


@dataclass(frozen=True)
class ReleaseVersion:
    """A version split into its release numbers and whether it is a prerelease."""

    release: tuple[int, int, int]
    prerelease: bool

    def plain(self) -> str:
        """The release numbers alone, e.g. "1.2.3"."""
        return ".".join(str(n) for n in self.release)


def parse_version(raw: object) -> ReleaseVersion | None:
    """*raw* as a version (a leading "v" allowed), or None if it isn't a plain one."""
    if not isinstance(raw, str):
        return None
    text = raw.strip().removeprefix("v")
    match = _RELEASE.match(text)
    if not match:
        return None
    rest = text[match.end() :]
    if rest and not (_SEMVER_PRERELEASE.fullmatch(rest) or _PEP440_PRERELEASE.fullmatch(rest)):
        return None
    major, minor, patch = (int(n) for n in match.groups())
    return ReleaseVersion((major, minor, patch), prerelease=bool(rest))


def is_newer(latest: ReleaseVersion, current: ReleaseVersion) -> bool:
    """Whether the stable release *latest* is newer than the running *current*.

    A prerelease of a version comes before it, so 1.2.0 is newer than 1.2.0-beta.1.
    Prereleases are never offered, so their order among themselves doesn't matter.
    """
    if latest.prerelease:
        return False
    if latest.release != current.release:
        return latest.release > current.release
    return current.prerelease


def release_page_url(version: ReleaseVersion | None) -> str:
    """The release notes for *version*, or the releases list. The URL is built from the
    parsed numbers, never from text in GitHub's response (as ``releasePageUrl`` in
    electron/src/updatePolicy.ts)."""
    return f"{RELEASES_URL}/tag/v{version.plain()}" if version else RELEASES_URL


class UpdateCheckError(Exception):
    """The latest release couldn't be found out: a short reason for the log."""


def fetch_latest_release(user_agent: str) -> ReleaseVersion | None:
    """The latest stable release on GitHub, or None if there isn't one yet.

    Raises UpdateCheckError for anything else: no network, a timeout, rate limiting, or
    a response that isn't a release.
    """
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": user_agent,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310  # nosec B310  # fixed https URL
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # no release published yet (or the repository is private)
            return None
        raise UpdateCheckError(f"GitHub answered HTTP {exc.code}") from exc
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise UpdateCheckError(f"could not reach GitHub ({reason})") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise UpdateCheckError("the response was too large")
    try:
        release = json.loads(body)
    except ValueError as exc:
        raise UpdateCheckError("the response was not JSON") from exc
    if not isinstance(release, dict):
        raise UpdateCheckError("the response was not a release")
    if release.get("draft") or release.get("prerelease"):
        # /releases/latest never returns these; ignore one rather than offer it.
        raise UpdateCheckError("the latest release is a draft or prerelease")
    version = parse_version(release.get("tag_name"))
    if version is None or version.prerelease:
        raise UpdateCheckError("the latest release has no usable version")
    return version


Fetcher = Callable[[], ReleaseVersion | None]


class UpdateChecker:
    """Checks for a newer release on a schedule and keeps the last good answer."""

    def __init__(
        self,
        current_version: str,
        *,
        enabled: bool,
        fetch: Fetcher | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._current_raw = current_version
        self._current = parse_version(current_version)
        self._enabled = enabled
        self._fetch = fetch or (lambda: fetch_latest_release(f"SceneAtlas/{current_version}"))
        self._clock = clock
        self._lock = threading.Lock()
        self._latest: ReleaseVersion | None = None
        self._last_checked: datetime | None = None
        self._failing = False
        self._announced: ReleaseVersion | None = None
        self._task: asyncio.Task | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def check_now(self) -> None:
        """Ask GitHub once and keep the answer. A failure keeps the previous one and is
        logged as a warning only when it follows a success (or is the first)."""
        if not self._enabled:
            return
        try:
            latest = self._fetch()
        except UpdateCheckError as exc:
            if not self._failing:
                logger.warning("Could not check for Scene Atlas updates: %s", exc)
            else:
                logger.debug("Update check failed again: %s", exc)
            self._failing = True
            return
        except Exception:
            # A bug, not the network: still never let it take the server down.
            logger.exception("Update check failed unexpectedly")
            self._failing = True
            return
        if self._failing:
            logger.info("Update check succeeded again")
        self._failing = False
        with self._lock:
            self._latest = latest
            self._last_checked = self._clock()
        if (
            latest is not None
            and latest != self._announced
            and self._current is not None
            and is_newer(latest, self._current)
        ):
            self._announced = latest
            logger.info(
                "Scene Atlas %s is available (running %s): %s",
                latest.plain(),
                self._current_raw,
                release_page_url(latest),
            )

    def status(self) -> UpdateCheckResponse:
        """The last good answer, as the API reports it (never checks)."""
        with self._lock:
            latest, last_checked = self._latest, self._last_checked
        available = bool(
            self._enabled and latest and self._current and is_newer(latest, self._current)
        )
        kind: UpdateStatusKind
        if not self._enabled:
            kind = "disabled"
        elif last_checked is None:
            kind = "pending"
        elif self._current is None:
            kind = "unknown"
        else:
            kind = "available" if available else "up_to_date"
        return UpdateCheckResponse(
            status=kind,
            current_version=self._current_raw,
            checks_enabled=self._enabled,
            latest_version=latest.plain() if latest else None,
            update_available=available,
            release_url=release_page_url(latest),
            last_checked=last_checked,
        )

    async def _run(self, first_delay: float, interval: float) -> None:
        delay = first_delay
        while True:
            await asyncio.sleep(delay)
            delay = interval
            await asyncio.to_thread(self.check_now)

    def start(
        self,
        first_delay: float = FIRST_CHECK_DELAY_SECONDS,
        interval: float = CHECK_INTERVAL_SECONDS,
    ) -> None:
        """Begin checking in the background (call from the running event loop). Does
        nothing when checks are off."""
        if not self._enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._run(first_delay, interval))
        logger.info("Checking for updates daily (CHECK_FOR_UPDATES=false turns this off)")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None


_checker: UpdateChecker | None = None
_checker_lock = threading.Lock()


def get_update_checker() -> UpdateChecker:
    """The process's checker, configured from settings on first use. It checks only in
    server mode with CHECK_FOR_UPDATES on; the desktop app's updater lives in Electron."""
    global _checker
    with _checker_lock:
        if _checker is None:
            from ..config import settings

            _checker = UpdateChecker(
                settings.app_version,
                enabled=settings.app_mode == "server" and settings.check_for_updates,
            )
        return _checker
