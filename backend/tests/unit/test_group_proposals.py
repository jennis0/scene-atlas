"""``group_jobs.propose``: an import's groups from its files, by detected type
(design/variant-grouping.md §3). Files that made no image (sorted out by Auto, failed,
duplicates) take no part: their type is a guess, so their names and folders must not sway
the groups. They are placed afterwards, with a map group or in the ungrouped proposal."""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from backend.app.services.variant_grouping import EmbeddingThresholds
from backend.pipeline.group_jobs import JobFile, Proposal, propose, propose_by_paths

from .variant_grouping.scenarios import SCENARIOS
from .variant_grouping.support import Look, features, parser

MAP, SCENE = "battlemap", "scene"


def mixed() -> dict[str, tuple[str, Look]]:
    """Maps and scenes of one maker: a scene in a map's folder, a folder of scene art."""
    files = {
        f"Maker/Keep/Keep_{v}.jpg": (MAP, Look("keep", "keep", k))
        for k, v in enumerate(["Day", "Night"])
    }
    files |= {
        "Maker/Keep/Keep Vista.jpg": (SCENE, Look("keep vista")),
        "Maker/Fort/Fort_Day.jpg": (MAP, Look("fort")),
        "Maker/Art/Tavern Day.jpg": (SCENE, Look("tavern")),
        "Maker/Art/Tavern Night.jpg": (SCENE, Look("tavern", variant=1)),
        "Maker/Art/castle.jpg": (SCENE, Look("castle")),
    }
    return files


IMPORTS = sorted([*SCENARIOS, "mixed"])


def typed(name: str) -> dict[str, tuple[str, Look]]:
    if name == "mixed":
        return mixed()
    return {path: (MAP, look) for path, look in SCENARIOS[name]().files.items()}


def skipped_beside(paths: list[str]) -> list[str]:
    """Files that made no image, planted where an import's tokens and assets sit: beside the
    maps, in a Tokens folder, named after a map, and loose at the root."""
    planted = ["Loose Token.png"]
    folders = sorted({str(PurePosixPath(p).parent) for p in paths})[:8]
    for folder in folders:
        first = next(PurePosixPath(p).stem for p in sorted(paths) if p.startswith(f"{folder}/"))
        planted += [
            f"{folder}/Goblin Token.png",
            f"{folder}/Tokens/Orc.png",
            f"{folder}/{first} Door Asset.png",
        ]
    return planted


def job_files(files: dict[str, tuple[str, Look]], skipped: list[str]) -> list[JobFile]:
    out: list[JobFile] = []
    for item, (path, (kind, _)) in enumerate(sorted(files.items())):
        out.append(_file(item, path, kind, image_id=1000 + item))
    for item, path in enumerate(skipped, start=len(out)):
        out.append(_file(item, path, "auto", image_id=None))
    return out


def _file(item: int, path: str, kind: str, image_id: int | None) -> JobFile:
    return JobFile(
        item_id=item,
        path=path,
        bucket=MAP if kind in (MAP, "auto") else SCENE,
        import_group_id=None,
        image_id=image_id,
        pending=image_id is not None,
        group_id=None,
        pixels=None,
        name=None,
        filename=PurePosixPath(path).name,
    )


def run(files: dict[str, tuple[str, Look]], skipped: list[str], content: bool) -> list[Proposal]:
    jobs = job_files(files, skipped)
    by_path = {f.path: f.item_id for f in jobs}
    if not content:
        return propose(jobs, {}, None, parser(), [])[0]
    found = {by_path[p]: features(look) for p, (_, look) in files.items()}
    return propose(jobs, found, EmbeddingThresholds(), parser(), [])[0]


def groups_of_images(proposals: list[Proposal], images: set[int]) -> set[tuple]:
    """The groups as the images see them: files, name, author and subgroups."""
    return {
        (
            frozenset(i for i in p.items if i in images),
            p.name,
            p.author,
            tuple(sorted((i, s) for i, s in p.subgroups.items() if i in images)),
            p.match_existing,
        )
        for p in proposals
        if not p.ungrouped and any(i in images for i in p.items)
    }


@pytest.mark.parametrize("content", [True, False], ids=["content", "paths"])
@pytest.mark.parametrize("name", IMPORTS)
def test_files_without_an_image_never_change_the_groups_or_their_names(name, content):
    files = typed(name)
    images = set(range(len(files)))
    alone = run(files, [], content)
    with_skipped = run(files, skipped_beside(list(files)), content)
    assert groups_of_images(with_skipped, images) == groups_of_images(alone, images)


@pytest.mark.parametrize("name", IMPORTS)
def test_every_file_is_in_exactly_one_proposal(name):
    files = typed(name)
    skipped = skipped_beside(list(files))
    proposals = run(files, skipped, content=True)
    items = [i for p in proposals for i in p.items]
    assert sorted(items) == list(range(len(files) + len(skipped)))
    assert sum(p.ungrouped for p in proposals) <= 1


def test_a_files_without_an_image_group_holds_only_files_without_an_image():
    files = mixed()
    proposals = run(files, skipped_beside(list(files)), content=True)
    (ungrouped,) = [p for p in proposals if p.ungrouped]
    assert ungrouped.items and min(ungrouped.items) >= len(files)
    assert not ungrouped.match_existing


def test_a_token_beside_one_map_is_shown_with_it_and_a_loose_one_is_ungrouped():
    files = mixed()
    skipped = ["Maker/Keep/Goblin Token.png", "Loose Token.png"]
    proposals = run(files, skipped, content=True)
    goblin, loose = len(files), len(files) + 1
    keep = next(p for p in proposals if goblin in p.items)
    assert not keep.ungrouped and keep.name == "Keep"
    assert next(p for p in proposals if loose in p.items).ungrouped


class TestByPaths:
    """The fallback for a job whose grouping keeps failing."""

    def test_files_without_an_image_are_ungrouped(self):
        files = mixed()
        skipped = ["Maker/Keep/Goblin Token.png"]
        jobs = job_files(files, skipped)
        proposals = propose_by_paths(jobs, parser(), [])
        (ungrouped,) = [p for p in proposals if p.ungrouped]
        assert ungrouped.items == (len(files),)

    def test_one_name_is_one_group_whatever_the_types(self):
        """The parser groups maps and scenes apart; one import never mints two groups of
        one name and author."""
        files = {
            "Golden Forest/GoldenForest_Night.jpg": (MAP, Look("a")),
            "Golden Forest/GoldenForest_Day.jpg": (MAP, Look("b")),
            "Golden Forest/GoldenForest_Vista.jpg": (SCENE, Look("c")),
        }
        proposals = propose_by_paths(job_files(files, []), parser(), [])
        names = [(p.name, p.author) for p in proposals]
        assert len(names) == len(set(names))
        assert any(len(p.items) == 3 for p in proposals)
