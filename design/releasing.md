# Releasing

How a version is set, built, checked and published, and how each kind of install picks it up ([ADR-024](decisions.md#adr-024-versions-in-the-repo-draft-releases-and-a-published-docker-image)). Updating the desktop app itself is in [electron.md](electron.md#updates); what the Release workflow tests is in [testing.md](testing.md).

## Making a release

1. **Bump the version in a PR.** `python scripts/release/release_version.py bump 0.2.0` sets it in every file that records it; commit, open a PR, merge. If the UI changed since the last release, re-take the docs screenshots in the same PR ([brand.md](brand.md#docs-screenshots)).
2. **Run the Release workflow** against `main` with `publish` ticked. Leave `accept_search_changes` off unless search results change on purpose ([testing.md](testing.md#upgrade-test)).
3. **Check the draft.** The run ends with a draft release `v0.2.0` holding its own installers, update metadata and Compose files; its summary links to it. Installed apps and the Docker `latest` tag ignore drafts.
4. **Publish the draft** on GitHub. Installed desktop apps find it within hours, and `release-published.yml` tags the Docker image `0.2.0` and `latest`.

Edit or publish a draft in GitHub's UI. Through the API (`PATCH /releases/{id}`), pass `tag_name` on every call: an update without it replaces the draft's tag with a placeholder (`untagged-…`), and publishing then creates that as a real tag. `release-published.yml` refuses a tag that isn't a version, so the image is never tagged with it; fix the release by setting it back to a draft with `tag_name`, deleting the stray tag, and publishing again (as happened to v0.1.1). `gh release edit --draft=false` doesn't publish with the `gh` some machines have; the API call does.

A run without `publish` does everything except push the image and create the draft: a full check of `main` between releases. Re-running for the same version replaces its draft; a published version can't be released again, so a fix is a new patch version.

## Versions

The version lives in the repo, in two places that must agree:

| File | Read by |
|---|---|
| `package.json` (and `package-lock.json`) | electron-builder (installer names, the app's version, `latest*.yml`), so electron-updater |
| `backend/__init__.py` | `pyproject.toml` (hatch dynamic version), `settings.app_version`, so the API, the logs and the server's update check |

`scripts/release/release_version.py` reads, bumps and checks them (standard library only). `backend/tests/unit/test_release_version.py` fails when they disagree, so a half-done bump doesn't reach `main`. `frontend/package.json` has no version: it is never released on its own.

Versions are plain semver: `1.2.3`, or `1.2.3-beta.1` for a prerelease. No build metadata (`+…`). Between releases `main` carries the last released version; builds from it aren't releases and the update checks treat them as that version.

**Prereleases** (a hyphen in the version) become GitHub prereleases. electron-updater on a release version skips them, and the Docker image gets its version tag but not `latest`. Nothing yet opts a desktop install into prereleases.

## The Release workflow

`.github/workflows/release.yml`, manual only. Jobs:

| Job | What | Notes |
|---|---|---|
| `preflight` | `release_version.py check`, plus `--publish` when publishing | Seconds. Publishing must run on `main`, and the version must be newer than every `v*` tag on origin (`git ls-remote`); it outputs `version` and `prerelease`. Also requires a reason when search changes are accepted. Everything else waits for it. |
| `test-*`, `e2e` | Full test suite, cross-platform unit tests, Playwright | |
| `build` | Electron installers per platform, packaged-app and upgrade tests (Windows) | Builds the repo's version as is; nothing rewrites it. |
| `docker` | Builds the CPU image, `smoke_docker.py`, pushes `sha-<commit>` when publishing | See below. |
| `publish` | Verifies the update metadata, adds the Compose files, creates the draft | `--prerelease` for a prerelease. An earlier draft for the same tag is deleted first. Release notes: the Docker tag, any accepted search change, then GitHub's generated notes. |

`concurrency: release` keeps two runs from racing to create the same draft.

## Docker image

`ghcr.io/jennis0/scene-atlas`, CPU only, linux/amd64. The GPU profile in `docker-compose.yml` still builds from a checkout.

| Tag | Pushed by | When |
|---|---|---|
| `sha-<commit>` | Release workflow, `docker` job | Every publishing run, after the smoke test |
| `<version>` | `release-published.yml` | When the draft is published (`imagetools create`, no rebuild) |
| `latest` | `release-published.yml` | The same, unless it's a prerelease |

So no one pulls a version that hasn't been published, and the published tag is the image the workflow tested. A discarded draft leaves only an unreferenced `sha-` tag.

**Runtime user.** One image serves everyone, so the user is chosen at run time: Compose runs it as `SCENE_ATLAS_UID:SCENE_ATLAS_GID` from `.env` (`user:`), and the user that must write the image bind mount is the host's. The image keeps a default `app` user (1000). `/app/data` is mode 0777 in the image, so a fresh named volume (which copies it) is writable by whatever user runs it; files inside belong to that user. `HOME=/tmp` covers libraries that cache under `~` when the user has no home. The container never runs as root. Changing `SCENE_ATLAS_UID` after the first start needs a `chown -R` of the volume (docs/deploy/server.md).

`scripts/build/smoke_docker.py` runs the image as `4321:4321` on a fresh volume and fails unless `/health` reports the database as `ok`, `/` reports the release version, and the UI is served. It does that twice: with `docker run`, then through `docker-compose.yml` with only the `.env` a user would write (port, `SCENE_ATLAS_UID`, `SCENE_ATLAS_VERSION`), which checks the Compose file's own settings. v0.1.0's Compose file quoted the `SCENE_ATLAS_CORS_ORIGINS` default inside the substitution, so the app got `'["…"]'`, couldn't parse it, and restarted forever unless `.env` set it; `docker run` never saw that.

**The first push** creates the GHCR package as private. Make it public once, in the package's settings on GitHub; the `org.opencontainers.image.source` label links it to the repo.

Each release also carries `docker-compose.yml` and `env.example` (renamed from `.env.example`: GitHub drops a leading dot from asset names), which the server docs download from `releases/latest/download/`.

## How each install updates

| Install | How it finds out | How it updates |
|---|---|---|
| Desktop (Windows, AppImage) | electron-updater, from the latest release's `latest*.yml` | Downloads and installs on restart ([electron.md](electron.md#updates)) |
| Desktop (macOS, .deb) | The same | Opens the release page |
| Docker (CPU) | The server's update check | `docker compose --profile cpu pull` and `up -d` (the profile is needed: plain `pull` skips a service under a profile) |
| Docker GPU, standalone | The server's update check | Check out the new tag and rebuild |

## Not done yet

- A GPU image, and arm64 images.
- The upgrade test on Linux and macOS in CI ([status-and-roadmap.md](status-and-roadmap.md)).
- A changelog beyond GitHub's generated notes.
