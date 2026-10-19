"""Check electron-updater metadata against the release assets before they are published.

electron-builder writes latest.yml (Windows), latest-mac.yml and latest-linux.yml next to
the installers. electron-updater trusts them completely: a wrong file name, size or sha512,
or a missing yml, breaks updates for everyone on that platform. This checks every yml
against the files that are about to be uploaded and reports every problem it finds.

Imports only the standard library and PyYAML, so the Release workflow can run it without
installing the project:

    uv run --no-project --with pyyaml python scripts/release/verify_update_metadata.py \
        --dir release --version 0.2.0 [--expect windows,macos,linux]

Exits non-zero with one line per problem, or prints a one-line summary per yml.
"""

import argparse
import base64
import hashlib
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

METADATA_FILES = {
    "windows": "latest.yml",
    "macos": "latest-mac.yml",
    "linux": "latest-linux.yml",
}

# Installers whose differential update needs a separate <name>.blockmap asset. AppImage
# embeds its blockmap; a deb has none.
BLOCKMAP_SUFFIXES = (".exe", ".dmg")

_CHUNK_SIZE = 1024 * 1024


def sha512_base64(path: Path) -> str:
    """Base64 of the raw sha512 digest, the form electron-builder writes."""
    digest = hashlib.sha512()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            digest.update(chunk)
    return base64.b64encode(digest.digest()).decode("ascii")


def collect_assets(root: Path) -> tuple[dict[str, Path], list[str]]:
    """Map asset name to path for every file under root. Names must be unique."""
    assets: dict[str, Path] = {}
    problems: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.name in assets:
            problems.append(f"duplicate asset name {path.name!r}: {assets[path.name]} and {path}")
            continue
        assets[path.name] = path
    for name in assets:
        if " " in name:
            problems.append(
                f"asset name {name!r} contains a space (GitHub rewrites it, so the yml url won't match)"
            )
    return assets, problems


class _Checker:
    """Checks yml files against one set of assets, hashing each asset at most once."""

    def __init__(self, assets: dict[str, Path], version: str) -> None:
        self.assets = assets
        self.version = version
        self._hashes: dict[str, str] = {}

    def _sha512(self, name: str) -> str:
        if name not in self._hashes:
            self._hashes[name] = sha512_base64(self.assets[name])
        return self._hashes[name]

    def check(self, yml_name: str, data: Any) -> list[str]:
        if not isinstance(data, dict):
            return [f"{yml_name}: not a YAML mapping"]

        problems: list[str] = []
        version = data.get("version")
        if str(version) != self.version:
            problems.append(f"{yml_name}: version {version!r} != expected {self.version!r}")
        if not data.get("releaseDate"):
            problems.append(f"{yml_name}: releaseDate missing")

        files = data.get("files")
        if not isinstance(files, list) or not files:
            problems.append(f"{yml_name}: files missing or empty")
            return problems

        for index, entry in enumerate(files):
            problems.extend(self._check_entry(yml_name, index, entry))
        problems.extend(self._check_legacy_fields(yml_name, data, files[0]))
        return problems

    def _check_entry(self, yml_name: str, index: int, entry: Any) -> list[str]:
        where = f"{yml_name}: files[{index}]"
        if not isinstance(entry, dict):
            return [f"{where}: not a mapping"]
        url = entry.get("url")
        if not isinstance(url, str) or not url:
            return [f"{where}: url missing"]
        where = f"{yml_name}: {url}"
        if url not in self.assets:
            return [f"{where}: no asset with this name"]

        problems: list[str] = []
        actual_size = self.assets[url].stat().st_size
        if entry.get("size") != actual_size:
            problems.append(f"{where}: size {entry.get('size')!r} != actual {actual_size}")
        expected_sha = entry.get("sha512")
        if not expected_sha:
            problems.append(f"{where}: sha512 missing")
        elif expected_sha != self._sha512(url):
            problems.append(f"{where}: sha512 does not match the asset")
        if url.endswith(BLOCKMAP_SUFFIXES) and f"{url}.blockmap" not in self.assets:
            problems.append(f"{where}: no {url}.blockmap asset")
        return problems

    @staticmethod
    def _check_legacy_fields(yml_name: str, data: dict[str, Any], first: Any) -> list[str]:
        """Top-level path/sha512 are what older electron-updater versions read."""
        if not isinstance(first, dict):
            return []
        problems: list[str] = []
        if data.get("path") != first.get("url"):
            problems.append(
                f"{yml_name}: path {data.get('path')!r} != files[0].url {first.get('url')!r}"
            )
        if data.get("sha512") != first.get("sha512"):
            problems.append(f"{yml_name}: top-level sha512 != files[0].sha512")
        return problems


def verify(root: Path, version: str, expect: Iterable[str]) -> list[str]:
    """Return every problem with the update metadata under root; empty means it's good."""
    if not root.is_dir():
        return [f"{root} is not a directory"]
    assets, problems = collect_assets(root)
    checker = _Checker(assets, version)
    for platform in expect:
        yml_name = METADATA_FILES[platform]
        if yml_name not in assets:
            problems.append(f"{yml_name}: missing (expected for {platform})")
            continue
        try:
            data = yaml.safe_load(assets[yml_name].read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            problems.append(f"{yml_name}: invalid YAML ({exc})")
            continue
        problems.extend(checker.check(yml_name, data))
    return problems


def _summary(root: Path, expect: Iterable[str]) -> list[str]:
    lines = []
    for platform in expect:
        yml_name = METADATA_FILES[platform]
        path = next(root.rglob(yml_name))
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        urls = ", ".join(entry["url"] for entry in data["files"])
        lines.append(f"OK {yml_name} {data['version']}: {urls}")
    return lines


def _parse_expect(value: str) -> list[str]:
    platforms = [p.strip() for p in value.split(",") if p.strip()]
    unknown = [p for p in platforms if p not in METADATA_FILES]
    if unknown or not platforms:
        raise argparse.ArgumentTypeError(
            f"expected a comma-separated subset of {','.join(METADATA_FILES)}, got {value!r}"
        )
    return platforms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dir",
        type=Path,
        required=True,
        help="folder holding the release assets (searched recursively)",
    )
    parser.add_argument("--version", required=True, help="release version, e.g. 0.2.0")
    parser.add_argument(
        "--expect",
        type=_parse_expect,
        default=list(METADATA_FILES),
        help="platforms whose yml must be present (default: windows,macos,linux)",
    )
    args = parser.parse_args(argv)

    problems = verify(args.dir, args.version, args.expect)
    if problems:
        for problem in problems:
            print(f"ERROR {problem}", file=sys.stderr)
        print(f"{len(problems)} problem(s) with the update metadata", file=sys.stderr)
        return 1
    for line in _summary(args.dir, args.expect):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
