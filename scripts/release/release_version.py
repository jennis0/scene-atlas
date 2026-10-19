"""The release version: show it, bump it, and check it before a release.

The version lives in two files, which must agree (design/releasing.md):

- package.json (with package-lock.json): the desktop app's version, which electron-builder
  stamps into the installers and electron-updater compares against the feed.
- backend/__init__.py: the backend's, which pyproject.toml reads (hatch dynamic version) and
  the API and the server's update check report.

Commands:

    python scripts/release/release_version.py show
    python scripts/release/release_version.py bump 0.2.0
    python scripts/release/release_version.py check [--publish]

``bump`` rewrites all of them, for a release PR. ``check`` is the Release workflow's first
step: the files agree and the version is a plain semver; with ``--publish``, it is also
newer than every release tag on origin. It writes ``version`` and ``prerelease`` to
``$GITHUB_OUTPUT`` when that is set. Standard library only, so it runs without the project.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PACKAGE_JSON = "package.json"
PACKAGE_LOCK = "package-lock.json"
BACKEND_INIT = "backend/__init__.py"

# semver.org without build metadata: three numbers without leading zeros, then optional
# dot-separated prerelease identifiers after the first hyphen. Each part is checked on its
# own rather than with one pattern with nested repetition.
_RELEASE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
_IDENTIFIER = re.compile(r"0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*")
_BACKEND_VERSION = re.compile(r'^__version__ = "([^"]*)"$', re.MULTILINE)


class VersionError(Exception):
    """A problem that stops a bump or a release; the message says what to fix."""


def parse(version: str) -> tuple[int, int, int, tuple[str, ...]]:
    """Split a plain semver into its numbers and prerelease identifiers."""
    release, _, pre = version.partition("-")
    match = _RELEASE.fullmatch(release)
    ids = tuple(pre.split(".")) if pre else ()
    if not match or not all(_IDENTIFIER.fullmatch(part) for part in ids) or version.endswith("-"):
        raise VersionError(f"{version!r} is not a version like 1.2.3 or 1.2.3-beta.1")
    major, minor, patch = (int(number) for number in match.groups())
    return major, minor, patch, ids


def _is_version(text: str) -> bool:
    try:
        parse(text)
    except VersionError:
        return False
    return True


def is_prerelease(version: str) -> bool:
    return bool(parse(version)[3])


def _precedence(version: str) -> tuple:
    """A sort key in semver precedence: a release sorts after its prereleases, numeric
    identifiers compare as numbers and before alphanumeric ones."""
    major, minor, patch, pre = parse(version)
    if not pre:
        return (major, minor, patch, 1, ())
    ids = tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in pre)
    return (major, minor, patch, 0, ids)


def is_newer(version: str, than: str) -> bool:
    return _precedence(version) > _precedence(than)


def read_versions(root: Path) -> dict[str, str]:
    """The version each file records, by file."""
    package = json.loads((root / PACKAGE_JSON).read_text(encoding="utf-8"))
    lock = json.loads((root / PACKAGE_LOCK).read_text(encoding="utf-8"))
    backend = _BACKEND_VERSION.search((root / BACKEND_INIT).read_text(encoding="utf-8"))
    return {
        PACKAGE_JSON: package.get("version", ""),
        PACKAGE_LOCK: lock.get("version", ""),
        f"{PACKAGE_LOCK} (packages[''])": lock.get("packages", {}).get("", {}).get("version", ""),
        BACKEND_INIT: backend.group(1) if backend else "",
    }


def current_version(root: Path) -> str:
    """The version, once every file agrees on it."""
    versions = read_versions(root)
    if len(set(versions.values())) != 1:
        found = ", ".join(f"{name}: {value or '(none)'}" for name, value in versions.items())
        raise VersionError(
            f"The version files disagree ({found}). Run "
            "scripts/release/release_version.py bump <version> to set them all."
        )
    version = next(iter(versions.values()))
    parse(version)
    return version


def _write_json(path: Path, data: dict) -> None:
    # npm's layout: two-space indent, non-ASCII kept, trailing newline.
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def bump(root: Path, version: str) -> None:
    """Set the version in every file that records it."""
    parse(version)
    package_path = root / PACKAGE_JSON
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["version"] = version
    _write_json(package_path, package)

    lock_path = root / PACKAGE_LOCK
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["version"] = version
    lock["packages"][""]["version"] = version
    _write_json(lock_path, lock)

    init_path = root / BACKEND_INIT
    text = init_path.read_text(encoding="utf-8")
    if not _BACKEND_VERSION.search(text):
        raise VersionError(f"No __version__ line in {BACKEND_INIT}")
    init_path.write_text(
        _BACKEND_VERSION.sub(f'__version__ = "{version}"', text, count=1), encoding="utf-8"
    )


def release_tags(ls_remote_output: str) -> list[str]:
    """The versions of the v<semver> tags in ``git ls-remote --tags`` output."""
    versions = []
    for line in ls_remote_output.splitlines():
        ref = line.split("\t")[-1].strip()
        name = ref.removeprefix("refs/tags/").removesuffix("^{}")
        if name.startswith("v") and _is_version(name[1:]):
            versions.append(name[1:])
    return sorted(set(versions), key=_precedence)


def check_publishable(version: str, released: Iterable[str]) -> None:
    """A release must be new and newer than every one before it: installed apps only ever
    move forward, and GitHub marks the newest-created release as latest."""
    released = list(released)
    if version in released:
        raise VersionError(f"v{version} is already released. Bump the version in a PR first.")
    newer = [other for other in released if not is_newer(version, other)]
    if newer:
        raise VersionError(
            f"v{version} is not newer than the released v{max(newer, key=_precedence)}."
        )


def _remote_tags(root: Path) -> str:
    result = subprocess.run(  # nosec B603 B607 - fixed git command, no user input
        ["git", "ls-remote", "--tags", "origin"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _write_outputs(outputs: dict[str, str]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None, root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show", help="print the version")
    bump_parser = commands.add_parser("bump", help="set the version in every file")
    bump_parser.add_argument("version")
    check_parser = commands.add_parser("check", help="check the version before a release")
    check_parser.add_argument(
        "--publish", action="store_true", help="also check it against the released tags"
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "show":
            print(current_version(root))
        elif args.command == "bump":
            bump(root, args.version)
            print(f"Version set to {args.version}. Commit it in a PR, merge, then release.")
        else:
            version = current_version(root)
            if args.publish:
                check_publishable(version, release_tags(_remote_tags(root)))
            prerelease = is_prerelease(version)
            _write_outputs({"version": version, "prerelease": str(prerelease).lower()})
            kind = "prerelease" if prerelease else "release"
            print(f"Version {version} ({kind}){' can be published' if args.publish else ''}")
    except VersionError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
