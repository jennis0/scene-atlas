"""The pre-publish check that electron-updater's yml files match the release assets."""

import base64
import hashlib
from pathlib import Path

import pytest
import yaml

from scripts.release.verify_update_metadata import main, sha512_base64, verify

VERSION = "0.2.0"
EXE = f"Scene-Atlas-Setup-{VERSION}.exe"
DMG = f"Scene-Atlas-{VERSION}-arm64.dmg"
APPIMAGE = f"Scene-Atlas-{VERSION}-x86_64.AppImage"
DEB = f"Scene-Atlas-{VERSION}-amd64.deb"


def _asset(directory: Path, name: str, content: bytes | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(content if content is not None else f"payload of {name}".encode())
    return path


def _entry(path: Path, **extra) -> dict:
    return {"url": path.name, "sha512": sha512_base64(path), "size": path.stat().st_size, **extra}


def _write_yml(directory: Path, name: str, entries: list[dict], **overrides) -> Path:
    data = {
        "version": VERSION,
        "files": entries,
        "path": entries[0]["url"],
        "sha512": entries[0]["sha512"],
        "releaseDate": "2026-10-19T12:00:00.000Z",
        **overrides,
    }
    data = {key: value for key, value in data.items() if value is not None}
    path = directory / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def release(tmp_path: Path) -> Path:
    """A good release laid out as `gh run download` leaves it: one folder per artifact."""
    root = tmp_path / "release"

    win = root / "scene-atlas-windows"
    exe = _asset(win, EXE)
    _asset(win, f"{EXE}.blockmap")
    _write_yml(win, "latest.yml", [_entry(exe, isAdminRightsRequired=False)])

    mac = root / "scene-atlas-macos"
    # dmg only: macOS just notifies until builds are signed, so there is no zip to install.
    dmg = _asset(mac, DMG)
    _asset(mac, f"{DMG}.blockmap")
    _write_yml(mac, "latest-mac.yml", [_entry(dmg)])

    linux = root / "scene-atlas-linux"
    appimage = _asset(linux, APPIMAGE)
    deb = _asset(linux, DEB)
    _write_yml(linux, "latest-linux.yml", [_entry(appimage, blockMapSize=123), _entry(deb)])
    return root


def _rewrite(yml: Path, **changes) -> None:
    data = yaml.safe_load(yml.read_text(encoding="utf-8"))
    data.update(changes)
    yml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_good_release_passes(release: Path, capsys):
    assert verify(release, VERSION, ["windows", "macos", "linux"]) == []
    assert main(["--dir", str(release), "--version", VERSION]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        f"OK latest.yml {VERSION}: {EXE}",
        f"OK latest-mac.yml {VERSION}: {DMG}",
        f"OK latest-linux.yml {VERSION}: {APPIMAGE}, {DEB}",
    ]


def test_sha512_is_base64_of_raw_digest(tmp_path: Path):
    content = b"x" * (3 * 1024 * 1024 + 7)  # spans several read chunks
    path = _asset(tmp_path, "big.bin", content)
    assert sha512_base64(path) == base64.b64encode(hashlib.sha512(content).digest()).decode()


def test_missing_yml(release: Path):
    (release / "scene-atlas-macos" / "latest-mac.yml").unlink()
    assert verify(release, VERSION, ["windows", "macos", "linux"]) == [
        "latest-mac.yml: missing (expected for macos)"
    ]


def test_expect_limits_which_yml_is_required(release: Path):
    (release / "scene-atlas-macos" / "latest-mac.yml").unlink()
    assert verify(release, VERSION, ["windows", "linux"]) == []
    assert main(["--dir", str(release), "--version", VERSION, "--expect", "windows,linux"]) == 0


def test_unknown_expect_platform_is_a_usage_error(release: Path):
    with pytest.raises(SystemExit) as exc:
        main(["--dir", str(release), "--version", VERSION, "--expect", "windows,solaris"])
    assert exc.value.code == 2


def test_version_mismatch(release: Path):
    problems = verify(release, "0.3.0", ["windows"])
    assert problems == ["latest.yml: version '0.2.0' != expected '0.3.0'"]


def test_url_without_matching_asset(release: Path):
    (release / "scene-atlas-windows" / EXE).rename(release / "scene-atlas-windows" / "renamed.exe")
    problems = verify(release, VERSION, ["windows"])
    assert f"latest.yml: {EXE}: no asset with this name" in problems


def test_size_mismatch(release: Path):
    _asset(release / "scene-atlas-linux", DEB, b"a different, longer payload")
    problems = verify(release, VERSION, ["linux"])
    assert any(p.startswith(f"latest-linux.yml: {DEB}: size ") for p in problems)
    assert f"latest-linux.yml: {DEB}: sha512 does not match the asset" in problems


def test_sha512_mismatch_with_same_size(release: Path):
    path = release / "scene-atlas-linux" / APPIMAGE
    original = path.read_bytes()
    path.write_bytes(original[:-1] + b"#")  # same size, stale hash
    assert verify(release, VERSION, ["linux"]) == [
        f"latest-linux.yml: {APPIMAGE}: sha512 does not match the asset"
    ]


def test_legacy_path_and_sha512_must_match_first_file(release: Path):
    _rewrite(release / "scene-atlas-linux" / "latest-linux.yml", path=DEB, sha512="stale")
    assert verify(release, VERSION, ["linux"]) == [
        f"latest-linux.yml: path '{DEB}' != files[0].url '{APPIMAGE}'",
        "latest-linux.yml: top-level sha512 != files[0].sha512",
    ]


def test_asset_name_with_space(release: Path):
    _asset(release / "scene-atlas-windows", "Scene Atlas Setup.exe")
    problems = verify(release, VERSION, ["windows"])
    assert len(problems) == 1
    assert "'Scene Atlas Setup.exe' contains a space" in problems[0]


@pytest.mark.parametrize(
    ("folder", "yml", "installer"),
    [
        ("scene-atlas-windows", "latest.yml", EXE),
        ("scene-atlas-macos", "latest-mac.yml", DMG),
    ],
)
def test_missing_blockmap(release: Path, folder: str, yml: str, installer: str):
    (release / folder / f"{installer}.blockmap").unlink()
    platform = "windows" if yml == "latest.yml" else "macos"
    assert verify(release, VERSION, [platform]) == [
        f"{yml}: {installer}: no {installer}.blockmap asset"
    ]


def test_appimage_and_deb_need_no_blockmap(release: Path):
    assert not list((release / "scene-atlas-linux").glob("*.blockmap"))
    assert verify(release, VERSION, ["linux"]) == []


def test_release_date_missing(release: Path):
    win = release / "scene-atlas-windows"
    _write_yml(win, "latest.yml", [_entry(win / EXE)], releaseDate=None)
    assert verify(release, VERSION, ["windows"]) == ["latest.yml: releaseDate missing"]


def test_duplicate_asset_names_across_folders(release: Path):
    _asset(release / "scene-atlas-linux", EXE)
    problems = verify(release, VERSION, ["windows"])
    assert len(problems) == 1
    assert problems[0].startswith(f"duplicate asset name '{EXE}'")


def test_malformed_files(release: Path):
    win = release / "scene-atlas-windows"
    (win / "latest.yml").write_text(f"version: {VERSION}\nreleaseDate: x\nfiles: []\n")
    assert verify(release, VERSION, ["windows"]) == ["latest.yml: files missing or empty"]
    (win / "latest.yml").write_text("files: [\n")
    assert verify(release, VERSION, ["windows"])[0].startswith("latest.yml: invalid YAML")


def test_every_problem_is_reported(release: Path, capsys):
    (release / "scene-atlas-macos" / "latest-mac.yml").unlink()
    (release / "scene-atlas-windows" / f"{EXE}.blockmap").unlink()
    _rewrite(release / "scene-atlas-linux" / "latest-linux.yml", version="0.1.9")
    assert main(["--dir", str(release), "--version", VERSION]) == 1
    err = capsys.readouterr().err.splitlines()
    assert err == [
        f"ERROR latest.yml: {EXE}: no {EXE}.blockmap asset",
        "ERROR latest-mac.yml: missing (expected for macos)",
        f"ERROR latest-linux.yml: version '0.1.9' != expected '{VERSION}'",
        "3 problem(s) with the update metadata",
    ]
