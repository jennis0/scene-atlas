"""Server-mode update check (backend/app/services/update_check.py, ADR-023).

GitHub is never contacted: fetches are faked, and ``HTTPSConnection`` is patched for the
tests of ``fetch_latest_release`` itself.
"""

import asyncio
import http.client
import io
import json
import logging
import socket
import ssl
from datetime import UTC, datetime

import pytest

from backend.app.services import update_check
from backend.app.services.update_check import (
    RELEASES_URL,
    ReleaseVersion,
    UpdateChecker,
    UpdateCheckError,
    fetch_latest_release,
    is_newer,
    parse_version,
    release_page_url,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def v(text: str) -> ReleaseVersion:
    parsed = parse_version(text)
    assert parsed is not None, text
    return parsed


class FakeFetch:
    """Returns (or raises) each queued outcome in turn and counts calls."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def checker(current="0.2.0", *outcomes, enabled=True) -> tuple[UpdateChecker, FakeFetch]:
    fetch = FakeFetch(*(outcomes or (None,)))
    return UpdateChecker(current, enabled=enabled, fetch=fetch, clock=lambda: NOW), fetch


# Versions


class TestParseVersion:
    @pytest.mark.parametrize(
        ("text", "release", "prerelease"),
        [
            ("0.2.0", (0, 2, 0), False),
            ("v1.10.3", (1, 10, 3), False),
            ("0.2.0-beta.1", (0, 2, 0), True),
            ("v0.2.0-rc.2", (0, 2, 0), True),
            ("0.2.0b1", (0, 2, 0), True),
            ("0.2.0rc1", (0, 2, 0), True),
            ("0.2.0a3", (0, 2, 0), True),
        ],
    )
    def test_releases_and_prereleases(self, text, release, prerelease):
        assert parse_version(text) == ReleaseVersion(release, prerelease)

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "dev",
            "1.2",
            "1.2.3.4",
            "0.2.1.dev3+g1a2b3c",  # a dev build
            "0.2.0+local",
            "0.2.0-",
            "0.2.0-beta 1",
            "0.2.0/../../evil",
            "0.2.0-beta.1?x=y",
            "0.2.0-" + "a" * 65,
            "1234567.0.0",
        ],
    )
    def test_anything_else_is_not_a_version(self, text):
        assert parse_version(text) is None

    @pytest.mark.parametrize("value", [None, 1, ["0.2.0"], {"tag": "0.2.0"}])
    def test_non_strings(self, value):
        assert parse_version(value) is None


class TestIsNewer:
    @pytest.mark.parametrize(
        ("latest", "current", "newer"),
        [
            ("0.2.0", "0.1.0", True),
            ("0.10.0", "0.9.0", True),  # numeric, not string, comparison
            ("1.0.0", "0.99.99", True),
            ("0.2.0", "0.2.0", False),
            ("0.1.0", "0.2.0", False),
            ("0.2.0", "0.2.0-beta.1", True),  # the release after its prerelease
            ("0.2.0", "0.2.0rc1", True),
            ("0.1.9", "0.2.0-beta.1", False),
            ("0.2.1", "0.2.0-beta.1", True),
        ],
    )
    def test_stable_latest(self, latest, current, newer):
        assert is_newer(v(latest), v(current)) is newer

    def test_a_prerelease_is_never_offered(self):
        assert not is_newer(v("0.3.0-beta.1"), v("0.2.0"))
        assert not is_newer(v("0.3.0-beta.2"), v("0.3.0-beta.1"))


class TestReleasePageUrl:
    def test_tag_page_from_the_parsed_numbers(self):
        assert release_page_url(v("v0.2.0")) == f"{RELEASES_URL}/tag/v0.2.0"

    def test_releases_list_without_a_version(self):
        assert release_page_url(None) == RELEASES_URL


# Fetching


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status: int):
        super().__init__(body)
        self.status = status


def patch_https(monkeypatch, result, status: int = 200):
    """Make GitHub answer *status* with *result* (bytes or a JSON-able object), or make
    the request raise *result*."""
    seen = {}

    class FakeConnection:
        def __init__(self, host, timeout, context):
            seen["host"], seen["timeout"], seen["context"] = host, timeout, context

        def request(self, method, path, headers):
            seen["method"], seen["path"], seen["headers"] = method, path, headers
            if isinstance(result, BaseException):
                raise result

        def getresponse(self):
            body = result if isinstance(result, bytes) else json.dumps(result).encode()
            return FakeResponse(body, status)

        def close(self):
            seen["closed"] = True

    monkeypatch.setattr(update_check.http.client, "HTTPSConnection", FakeConnection)
    return seen


class TestFetchLatestRelease:
    def test_returns_the_tagged_version(self, monkeypatch):
        seen = patch_https(
            monkeypatch,
            {"tag_name": "v0.3.0", "draft": False, "prerelease": False, "html_url": "x"},
        )
        assert fetch_latest_release("SceneAtlas/0.2.0") == v("0.3.0")
        assert seen["host"] == "api.github.com"
        assert (seen["method"], seen["path"]) == (
            "GET",
            "/repos/jennis0/scene-atlas/releases/latest",
        )
        assert seen["headers"]["User-Agent"] == "SceneAtlas/0.2.0"
        assert seen["timeout"] == update_check.REQUEST_TIMEOUT_SECONDS
        assert seen["context"].verify_mode == ssl.CERT_REQUIRED
        assert seen["context"].check_hostname
        assert seen["closed"]

    def test_no_releases_yet(self, monkeypatch):
        patch_https(monkeypatch, {"message": "Not Found"}, status=404)
        assert fetch_latest_release("ua") is None

    @pytest.mark.parametrize("status", [301, 403, 429, 500])  # moved, rate limited, broken
    def test_other_statuses(self, monkeypatch, status):
        seen = patch_https(monkeypatch, {"message": "x"}, status=status)
        with pytest.raises(UpdateCheckError, match=f"HTTP {status}"):
            fetch_latest_release("ua")
        assert seen["closed"]

    @pytest.mark.parametrize(
        "failure",
        [
            socket.gaierror("Name or service not known"),  # offline / air-gapped
            ssl.SSLCertVerificationError("certificate verify failed"),
            http.client.RemoteDisconnected("closed"),
            TimeoutError("timed out"),
            ConnectionResetError("reset"),
        ],
    )
    def test_network_failures(self, monkeypatch, failure):
        seen = patch_https(monkeypatch, failure)
        with pytest.raises(UpdateCheckError):
            fetch_latest_release("ua")
        assert seen["closed"]

    @pytest.mark.parametrize(
        "body",
        [
            b"<html>not json</html>",
            b"",
            ["v0.3.0"],
            {"tag_name": None},
            {"tag_name": "latest"},
            {"tag_name": "v0.3.0", "prerelease": True},
            {"tag_name": "v0.3.0", "draft": True},
            {"tag_name": "v0.3.0-beta.1"},
            {"message": "API rate limit exceeded"},
        ],
    )
    def test_malformed_or_unusable_responses(self, monkeypatch, body):
        patch_https(monkeypatch, body)
        with pytest.raises(UpdateCheckError):
            fetch_latest_release("ua")

    def test_oversized_response(self, monkeypatch):
        patch_https(monkeypatch, b" " * (update_check.MAX_RESPONSE_BYTES + 1))
        with pytest.raises(UpdateCheckError, match="too large"):
            fetch_latest_release("ua")


# The checker


class TestUpdateChecker:
    def test_disabled_never_fetches(self):
        c, fetch = checker("0.2.0", v("0.3.0"), enabled=False)
        c.check_now()
        assert fetch.calls == 0
        status = c.status()
        assert status.status == "disabled"
        assert not status.checks_enabled
        assert not status.update_available
        assert status.latest_version is None
        assert status.last_checked is None

    def test_pending_until_a_check_succeeds(self):
        c, _ = checker("0.2.0", UpdateCheckError("offline"))
        assert c.status().status == "pending"
        c.check_now()
        status = c.status()
        assert status.status == "pending"
        assert status.checks_enabled
        assert status.release_url == RELEASES_URL

    def test_newer_release_available(self):
        c, fetch = checker("0.2.0", v("0.3.0"))
        c.check_now()
        status = c.status()
        assert fetch.calls == 1
        assert status.status == "available"
        assert status.update_available
        assert status.current_version == "0.2.0"
        assert status.latest_version == "0.3.0"
        assert status.release_url == f"{RELEASES_URL}/tag/v0.3.0"
        assert status.last_checked == NOW

    def test_up_to_date(self):
        c, _ = checker("0.3.0", v("0.3.0"))
        c.check_now()
        status = c.status()
        assert status.status == "up_to_date"
        assert not status.update_available
        assert status.latest_version == "0.3.0"

    def test_no_releases_published_is_up_to_date(self):
        c, _ = checker("0.2.0", None)
        c.check_now()
        status = c.status()
        assert status.status == "up_to_date"
        assert status.latest_version is None
        assert status.release_url == RELEASES_URL

    def test_prerelease_install_is_offered_the_release(self):
        c, _ = checker("0.3.0-beta.2", v("0.3.0"))
        c.check_now()
        assert c.status().update_available

    def test_dev_build_is_not_compared(self):
        c, _ = checker("0.3.0.dev4+gabc123", v("9.0.0"))
        c.check_now()
        status = c.status()
        assert status.status == "unknown"
        assert not status.update_available
        assert status.latest_version == "9.0.0"

    def test_failure_keeps_the_last_good_result(self):
        c, _ = checker("0.2.0", v("0.3.0"), UpdateCheckError("offline"))
        c.check_now()
        c.check_now()
        status = c.status()
        assert status.status == "available"
        assert status.latest_version == "0.3.0"
        assert status.last_checked == NOW

    def test_unexpected_errors_do_not_escape(self):
        c, _ = checker("0.2.0", RuntimeError("bug"))
        c.check_now()
        assert c.status().status == "pending"

    def test_failures_warn_once_per_streak(self, caplog):
        c, _ = checker(
            "0.2.0",
            UpdateCheckError("offline"),
            UpdateCheckError("offline"),
            UpdateCheckError("offline"),
            v("0.2.0"),
            UpdateCheckError("rate limited"),
        )
        with caplog.at_level(logging.DEBUG, logger=update_check.__name__):
            for _ in range(5):
                c.check_now()
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == [
            "Could not check for Scene Atlas updates: offline",
            "Could not check for Scene Atlas updates: rate limited",
        ]

    def test_logs_a_new_version_once(self, caplog):
        c, _ = checker("0.2.0", v("0.3.0"))
        with caplog.at_level(logging.INFO, logger=update_check.__name__):
            c.check_now()
            c.check_now()
        found = [r for r in caplog.records if "is available" in r.getMessage()]
        assert len(found) == 1

    async def test_schedule_checks_after_the_delay_and_repeats(self):
        c, fetch = checker("0.2.0", v("0.3.0"))
        c.start(first_delay=0.01, interval=0.01)
        for _ in range(200):
            if fetch.calls >= 2:
                break
            await asyncio.sleep(0.01)
        await c.stop()
        assert fetch.calls >= 2
        assert c.status().update_available

    async def test_start_does_nothing_when_disabled(self):
        c, fetch = checker("0.2.0", v("0.3.0"), enabled=False)
        c.start(first_delay=0, interval=0.01)
        await asyncio.sleep(0.05)
        await c.stop()
        assert fetch.calls == 0

    async def test_startup_is_not_blocked(self):
        c, fetch = checker("0.2.0", v("0.3.0"))
        c.start()  # the real first delay: nothing runs yet
        await asyncio.sleep(0)
        assert fetch.calls == 0
        await c.stop()


class TestConfiguredChecker:
    @pytest.fixture(autouse=True)
    def fresh_singleton(self, monkeypatch):
        monkeypatch.setattr(update_check, "_checker", None)

    @pytest.mark.parametrize(
        ("mode", "check_for_updates", "enabled"),
        [
            ("server", True, True),
            ("server", False, False),
            ("app", True, False),  # Electron checks for itself
            ("app", False, False),
        ],
    )
    def test_checks_only_in_server_mode_when_allowed(
        self, monkeypatch, mode, check_for_updates, enabled
    ):
        from backend.app.config import settings

        monkeypatch.setattr(settings, "app_mode", mode)
        monkeypatch.setattr(settings, "check_for_updates", check_for_updates)
        assert update_check.get_update_checker().enabled is enabled

    def test_env_var_turns_checks_off(self, monkeypatch):
        from backend.app.config import Settings

        monkeypatch.setenv("CHECK_FOR_UPDATES", "false")
        assert Settings().check_for_updates is False
        monkeypatch.delenv("CHECK_FOR_UPDATES")
        assert Settings(_env_file=None).check_for_updates is True  # pyright: ignore[reportCallIssue]


class TestEndpoint:
    def test_reports_the_cached_result_without_checking(self, test_client, monkeypatch):
        c, fetch = checker("0.2.0", v("0.3.0"))
        c.check_now()
        monkeypatch.setattr(update_check, "_checker", c)

        body = test_client.get("/api/v1/system/updates").json()

        assert fetch.calls == 1  # the request didn't check again
        assert body == {
            "status": "available",
            "current_version": "0.2.0",
            "checks_enabled": True,
            "latest_version": "0.3.0",
            "update_available": True,
            "release_url": f"{RELEASES_URL}/tag/v0.3.0",
            "last_checked": "2026-10-19T12:00:00Z",
        }

    def test_disabled_in_tests(self, test_client, monkeypatch):
        monkeypatch.setattr(update_check, "_checker", None)
        body = test_client.get("/api/v1/system/updates").json()
        assert body["status"] == "disabled"
        assert body["checks_enabled"] is False
