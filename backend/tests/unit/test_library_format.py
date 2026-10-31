"""The scene-atlas.jsonl format (design/export-backup-move.md §2): what the writer puts in
each kind of file, that the reader reads it back, and that the reader refuses hostile or
broken input."""

import gzip
import io
import json
from datetime import datetime

import numpy as np
import pytest
from sqlalchemy import insert, select

from backend.app.models import Image, ImageGroup, Tag
from backend.app.models.database import AppSetting, Color, LibrarySource, SourceFile
from backend.pipeline import library_format as lf
from backend.pipeline.naming import ReadableLayout, layout_image

H = "ab" * 32  # a valid sha256


@pytest.fixture
def library(tmp_db):
    """A group of two, a group of one, an ungrouped image, an image awaiting grouping
    (left out of every file) and a linked file."""
    _engine, SessionLocal = tmp_db
    with SessionLocal() as db:
        forest = ImageGroup(base_name="Golden Forest", author="Czepeku")
        tavern = ImageGroup(base_name="Lone Tavern", author="Czepeku")
        db.add_all([forest, tavern])
        db.flush()
        day = Image(
            filename="day.png",
            storage_key="aa" * 16 + ".webp",
            thumbnail_key="aa" * 16 + "_400x400.jpg",
            name="Day",
            author="Czepeku",
            group_id=forest.id,
            image_type="battlemap",
            gridded=True,
            grid_type="square",
            grid_width=30,
            grid_height=30,
            grid_source="user",
            content_hash=H,
            stored_hash="cd" * 32,
            created_at=datetime(2026, 10, 1, 12, 0),
        )
        night = Image(
            filename="night.png", storage_key="bb" * 16 + ".png", name="Night",
            author="Czepeku", group_id=forest.id, gridded=False, content_hash=H,
        )  # fmt: skip
        inn = Image(
            filename="inn.png", storage_key="cc" * 16 + ".png", name="Lone Tavern",
            author="Czepeku", group_id=tavern.id, image_type="scene",
        )  # fmt: skip
        loose = Image(filename="loose.jpg", storage_key="dd" * 16 + ".jpg", name="Harbour")
        waiting = Image(filename="w.jpg", storage_key="ee" * 16 + ".jpg", awaiting_grouping=True)
        db.add_all([day, night, inn, loose, waiting])
        db.flush()
        forest.primary_image_id = night.id
        db.add_all(
            [
                Tag(image_id=day.id, category="season", value="summer", source="manual"),
                Tag(
                    image_id=day.id, category="biome", value="forest", source="auto", confidence=0.8
                ),
                Color(image_id=day.id, color_hex="#2f4a1c", percentage=31.0, color_order=1),
                AppSetting(key="stored_format", value_json='"webp"'),
            ]
        )
        source = LibrarySource(kind="folder", location="/maps", state="online")
        db.add(source)
        db.flush()
        db.add(
            SourceFile(source_id=source.id, rel_key="A/b.png", size=10, mtime_ns=5, state="removed")
        )
        db.commit()
        ids = {
            "day": day.id,
            "night": night.id,
            "inn": inn.id,
            "loose": loose.id,
            "waiting": waiting.id,
        }
    return SessionLocal, ids


def _vectors(ids):
    return {i: [float(i), 0.5] for i in ids}


def _library_file(SessionLocal) -> str:
    with SessionLocal() as db:
        return "".join(
            lf.library_lines(
                db,
                app_version="0.2.0",
                library_id="lib-1",
                model={"name": "small", "encoder_sha256": H, "dim": 2},
                vectors=_vectors,
            )
        )


def test_library_file_round_trips(library):
    SessionLocal, ids = library
    lines = list(lf.read_lines(io.StringIO(_library_file(SessionLocal))))

    header = lines[0]
    assert isinstance(header, lf.Header)
    assert header.kind == "library"
    assert header.library_id == "lib-1"
    assert header.model is not None and header.model.dim == 2
    assert header.settings == {"stored_format": "webp"}
    assert "season" in {c.name for c in header.tag_categories}

    groups = [ln for ln in lines if isinstance(ln, lf.GroupLine)]
    assert [g.group.base_name if g.group else None for g in groups] == [
        "Golden Forest",
        "Lone Tavern",
        None,
    ]
    forest = groups[0]
    assert forest.group is not None and forest.group.id is not None
    assert [i.id for i in forest.images] == [ids["day"], ids["night"]]
    assert forest.group.primary == 1  # Night
    day = forest.images[0]
    assert day.grid.type == "square" and day.grid.width == 30 and day.grid.source == "user"
    assert {(t.category, t.value, t.source) for t in day.tags} == {
        ("season", "summer", "manual"),
        ("biome", "forest", "auto"),
    }
    assert day.colors == [("#2f4a1c", 31.0)]
    assert day.stored_hash == "cd" * 32  # the stored file's hash, not the upload's
    assert forest.images[1].stored_hash == H  # no stored_hash: the content hash stands in
    assert day.storage_key == "aa" * 16 + ".webp"
    assert day.path is None
    assert day.vector is not None
    np.testing.assert_array_equal(lf.decode_vector(day.vector, 2), [float(ids["day"]), 0.5])

    all_ids = {i.id for g in groups for i in g.images}
    assert ids["waiting"] not in all_ids  # mid-import images are never exported

    (files,) = [ln for ln in lines if isinstance(ln, lf.SourceFilesLine)]
    assert [(f.rel_key, f.state) for f in files.source_files] == [("A/b.png", "removed")]


def test_groups_file_has_paths_and_no_library_fields(library):
    SessionLocal, ids = library
    layout = ReadableLayout()
    with SessionLocal() as db:
        lines = list(
            lf.group_lines(
                db,
                kind=lf.KIND_GROUPS,
                condition=Image.id.in_([ids["day"], ids["night"], ids["loose"]]),
                place=lambda g, imgs: layout.place_group(
                    g.base_name if g else None,
                    g.author if g else imgs[0].author,
                    [layout_image(i) for i in imgs],
                ),
            )
        )
    text = "".join(lf.dump_line(ln) for ln in lines)
    assert "storage_key" not in text and '"id"' not in text
    paths = [i["path"] for ln in lines for i in ln["images"]]
    assert paths == [
        "Czepeku_Golden Forest/Czepeku_Golden Forest_Day_G30x30[forest,summer].webp",
        "Czepeku_Golden Forest/Czepeku_Golden Forest_Night_GL.png",
        "Harbour.jpg",
    ]


def test_every_new_group_gets_a_distinct_uid(tmp_db):
    """The model's default covers ORM adds and the grouping phase's Core insert alike."""
    _engine, SessionLocal = tmp_db
    with SessionLocal() as db:
        db.add(ImageGroup(base_name="A"))
        db.execute(insert(ImageGroup), [{"base_name": "B"}, {"base_name": "C"}])
        db.commit()
        uids = db.scalars(select(ImageGroup.uid)).all()
    assert len(uids) == 3 and len(set(uids)) == 3 and all(uids)


def test_gzipped_files_are_read(tmp_path, library):
    SessionLocal, _ = library
    path = tmp_path / "export.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fp:
        fp.write(_library_file(SessionLocal))
    with lf.open_file(path) as fp:
        assert sum(isinstance(ln, lf.GroupLine) for ln in lf.read_lines(fp)) == 3


def _header(**changes) -> str:
    header = {
        "format": "scene-atlas",
        "version": "1.0",
        "kind": "groups",
        "app_version": "0.2.0",
        "created_at": "2026-10-31T00:00:00+00:00",
    }
    return json.dumps(header | changes) + "\n"


def _group(**image) -> str:
    entry = {"filename": "a.png", "image_type": "battlemap"} | image
    return json.dumps({"group": None, "images": [entry]}) + "\n"


def _read(text: str) -> list:
    return list(lf.read_lines(io.StringIO(text)))


class TestReaderRefuses:
    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("", "empty"),
            ("not json\n", "not JSON"),
            ("[1, 2]\n", "not a JSON object"),
            (_header(format="other"), "format"),
            (_header(version="2.0"), "version 2.0 is not supported"),
            (_header() + _group(storage_key="../../etc/passwd"), "storage_key"),
            (_header() + _group(image_type="token"), "image_type"),
            (_header() + _group(grid={"width": -3}), "grid.width"),
            (_header() + _group(tags=[{"category": "", "value": "x"}]), "tags.0.category"),
            (_header() + _group(name="x" * 5_000), "name"),
        ],
    )
    def test_invalid_input(self, text, message):
        with pytest.raises(lf.FormatError, match=message):
            _read(text)

    def test_error_names_the_line(self):
        with pytest.raises(lf.FormatError) as info:
            _read(_header() + _group() + _group(image_type="token"))
        assert info.value.line == 3

    def test_a_line_that_is_too_long(self, monkeypatch, tmp_path):
        monkeypatch.setattr(lf, "MAX_LINE_BYTES", 100)
        path = tmp_path / "f.jsonl"
        path.write_text(_header(), encoding="utf-8")
        with lf.open_file(path) as fp, pytest.raises(lf.FormatError, match="too long"):
            list(lf.read_lines(fp))


def test_newer_minor_versions_and_unknown_lines_are_read(tmp_path):
    text = (
        _header(version="1.7", future_field=1)
        + json.dumps({"something_new": []})
        + "\n"
        + _group(new_image_field="x")
    )
    lines = _read(text)
    assert [type(ln) for ln in lines] == [lf.Header, lf.GroupLine]


def test_decode_vector_checks_its_length():
    text = lf.encode_vector([1.0, 2.0, 3.0])
    np.testing.assert_array_equal(lf.decode_vector(text, 3), [1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="expected 4"):
        lf.decode_vector(text, 4)
