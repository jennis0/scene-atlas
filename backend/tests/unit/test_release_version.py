"""The release version: one value across the files that record it, and the release checks."""

import json
import shutil
from pathlib import Path

import pytest

import backend
from backend.app.config import Settings
from scripts.release import release_version
from scripts.release.release_version import (
    REPO_ROOT,
    VersionError,
    bump,
    check_publishable,
    current_version,
    is_newer,
    is_prerelease,
    main,
    parse,
    release_tags,
)

VERSION_FILES = ("package.json", "package-lock.json", "backend/__init__.py")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A copy of the repo's version files."""
    for name in VERSION_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / name, target)
    return tmp_path


# ── The repo itself ─────────────────────────────────────────────────────────


def test_the_version_files_agree():
    """Every place that records the version holds the same one (bump them together)."""
    version = current_version(REPO_ROOT)
    assert backend.__version__ == version
    assert Settings.model_fields["app_version"].default == version


def test_the_frontend_has_no_version_of_its_own():
    """It isn't released on its own, so a version there would only drift."""
    package = json.loads((REPO_ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    assert "version" not in package


# ── Parsing and precedence ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.1.0", (0, 1, 0, ())),
        ("10.20.30", (10, 20, 30, ())),
        ("1.2.3-beta.1", (1, 2, 3, ("beta", "1"))),
        ("1.2.3-rc-1.0a", (1, 2, 3, ("rc-1", "0a"))),
    ],
)
def test_parse_accepts_plain_semver(version, expected):
    assert parse(version) == expected


@pytest.mark.parametrize(
    "version",
    ["", "1.2", "1.2.3.4", "01.2.3", "1.02.3", "v1.2.3", "1.2.3-", "1.2.3-a..b", "1.2.3-01",
     "1.2.3+build", "1.2.3-beta!", " 1.2.3"],
)  # fmt: skip
def test_parse_rejects_anything_else(version):
    with pytest.raises(VersionError):
        parse(version)


def test_precedence_follows_semver():
    # The ordering example from semver.org, item 11.
    ordered = [
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
        "1.0.1",
        "1.1.0",
        "2.0.0",
    ]
    for lower, higher in zip(ordered, ordered[1:], strict=False):
        assert is_newer(higher, lower), f"{higher} should be newer than {lower}"
        assert not is_newer(lower, higher)
    assert not is_newer("1.0.0", "1.0.0")


def test_is_prerelease():
    assert is_prerelease("0.2.0-beta.1")
    assert not is_prerelease("0.2.0")


# ── Release tags and the publish check ──────────────────────────────────────


def test_release_tags_reads_version_tags_from_ls_remote():
    output = (
        "aaa\trefs/tags/v0.1.0\n"
        "bbb\trefs/tags/v0.1.0^{}\n"
        "ccc\trefs/tags/v0.2.0-beta.1\n"
        "ddd\trefs/tags/v0.10.0\n"
        "eee\trefs/tags/nightly\n"
        "fff\trefs/tags/v1.2\n"
        "ggg\trefs/tags/0.3.0\n"
    )
    assert release_tags(output) == ["0.1.0", "0.2.0-beta.1", "0.10.0"]


def test_check_publishable_accepts_a_newer_version():
    check_publishable("0.2.0", ["0.1.0", "0.2.0-beta.1"])
    check_publishable("0.1.0", [])


def test_check_publishable_rejects_an_existing_release():
    with pytest.raises(VersionError, match="already released"):
        check_publishable("0.1.0", ["0.1.0"])


@pytest.mark.parametrize("version", ["0.1.5", "0.2.0-beta.1"])
def test_check_publishable_rejects_an_older_version(version):
    with pytest.raises(VersionError, match="not newer than the released v0.2.0"):
        check_publishable(version, ["0.1.0", "0.2.0"])


# ── Bumping ─────────────────────────────────────────────────────────────────


def test_bump_sets_every_file(repo: Path):
    bump(repo, "0.2.0-beta.1")
    assert current_version(repo) == "0.2.0-beta.1"
    lock = json.loads((repo / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["version"] == lock["packages"][""]["version"] == "0.2.0-beta.1"


def test_bump_keeps_npm_formatting(repo: Path):
    """Only the version lines change, so a bump PR's diff is just the bump."""
    before = {name: (repo / name).read_text(encoding="utf-8") for name in VERSION_FILES}
    bump(repo, "9.9.9")
    for name in VERSION_FILES:
        old_lines = before[name].splitlines(keepends=True)
        new_lines = (repo / name).read_text(encoding="utf-8").splitlines(keepends=True)
        assert len(new_lines) == len(old_lines), name
        changed = [new for old, new in zip(old_lines, new_lines, strict=True) if old != new]
        expected = 2 if name == "package-lock.json" else 1
        assert len(changed) == expected, name
        assert all("version" in line and '"9.9.9"' in line for line in changed), name


def test_bump_rejects_a_bad_version(repo: Path):
    before = (repo / "package.json").read_text(encoding="utf-8")
    with pytest.raises(VersionError):
        bump(repo, "0.2")
    assert (repo / "package.json").read_text(encoding="utf-8") == before


def test_disagreeing_files_name_each_version(repo: Path):
    init = repo / "backend/__init__.py"
    init.write_text('__version__ = "7.0.0"\n', encoding="utf-8")
    with pytest.raises(VersionError, match=r"backend/__init__\.py: 7\.0\.0"):
        current_version(repo)


# ── Command line ────────────────────────────────────────────────────────────


def test_check_writes_workflow_outputs(repo, monkeypatch, tmp_path, capsys):
    bump(repo, "0.3.0-rc.1")
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(release_version, "_remote_tags", lambda root: "x\trefs/tags/v0.2.0\n")

    assert main(["check", "--publish"], root=repo) == 0

    assert output.read_text(encoding="utf-8") == "version=0.3.0-rc.1\nprerelease=true\n"
    assert "can be published" in capsys.readouterr().out


def test_check_fails_when_already_released(repo, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    version = current_version(repo)
    monkeypatch.setattr(release_version, "_remote_tags", lambda root: f"x\trefs/tags/v{version}\n")

    assert main(["check", "--publish"], root=repo) == 1
    assert "already released" in capsys.readouterr().err


def test_check_without_publish_never_asks_git(repo, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    def fail(root):
        raise AssertionError("git was called")

    monkeypatch.setattr(release_version, "_remote_tags", fail)
    assert main(["check"], root=repo) == 0


def test_show_and_bump(repo, capsys):
    assert main(["bump", "1.0.0"], root=repo) == 0
    assert main(["show"], root=repo) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "1.0.0"
    assert main(["bump", "nope"], root=repo) == 1
