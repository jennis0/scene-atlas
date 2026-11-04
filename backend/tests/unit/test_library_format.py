"""The scene-atlas.jsonl format (design/export-backup-move.md §2): what the writer puts in
each kind of file, that the reader reads back exactly what was written (including rows at
the edges of what the database holds), and that the reader refuses hostile input."""

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
    """A group of two, a group of one, an ungrouped image, a linked video, an image
    awaiting grouping (left out of every file) and three linked files."""
    _engine, SessionLocal = tmp_db
    with SessionLocal() as db:
        forest = ImageGroup(base_name="Golden Forest", author="Czepeku")
        tavern = ImageGroup(base_name="Lone Tavern", author="Czepeku")
        db.add_all([forest, tavern])
        source = LibrarySource(kind="folder", location="/maps", state="online")
        db.add(source)
        db.flush()
        linked_file = SourceFile(source_id=source.id, rel_key="A/clip.mp4", size=9, mtime_ns=7)
        db.add(linked_file)
        db.flush()
        day = Image(
            filename="day.png",
            storage_key="aa" * 16 + ".webp",
            thumbnail_key="aa" * 16 + "_400x400.jpg",
            name="Day",
            author="Czepeku",
            group_id=forest.id,
            subgroup="Summer",
            image_type="battlemap",
            gridded=True,
            grid_type="square",
            grid_width=30,
            grid_height=30,
            grid_source="user",
            content_hash=H,
            stored_hash="cd" * 32,
            phash=-(2**63),
            created_at=datetime(2026, 10, 1, 12, 0),
        )
        night = Image(
            filename="night.png", storage_key="bb" * 16 + ".png", name="Night",
            author="Czepeku", group_id=forest.id, gridded=False, stored_hash=H,
        )  # fmt: skip
        inn = Image(
            filename="inn.png", storage_key="cc" * 16 + ".png", name="Lone Tavern",
            author="Czepeku", group_id=tavern.id, image_type="scene",
        )  # fmt: skip
        loose = Image(filename="loose.jpg", storage_key="dd" * 16 + ".jpg", name="Harbour")
        clip = Image(
            filename="clip.mp4", source_file_id=linked_file.id, name="Clip", media_type="video",
        )  # fmt: skip
        waiting = Image(filename="w.jpg", storage_key="ee" * 16 + ".jpg", awaiting_grouping=True)
        db.add_all([day, night, inn, loose, clip, waiting])
        db.flush()
        forest.primary_image_id = night.id
        linked_file.state, linked_file.image_id = "image", clip.id
        db.add_all(
            [
                Tag(image_id=day.id, category="season", value="summer", source="manual"),
                Tag(
                    image_id=day.id, category="biome", value="forest", source="auto", confidence=0.8
                ),
                Color(image_id=day.id, color_hex="#2f4a1c", percentage=31.0, color_order=1),
                AppSetting(key="stored_format", value_json='"webp"'),
                SourceFile(
                    source_id=source.id, rel_key="A/b.png", size=10, mtime_ns=5, state="removed"
                ),
                # The image is mid-import, so it isn't exported: neither may this row point at it
                SourceFile(
                    source_id=source.id,
                    rel_key="A/w.jpg",
                    size=3,
                    mtime_ns=1,
                    state="image",
                    image_id=waiting.id,
                ),
            ]
        )
        db.commit()
        ids = {
            "day": day.id,
            "night": night.id,
            "inn": inn.id,
            "loose": loose.id,
            "clip": clip.id,
            "waiting": waiting.id,
        }
    return SessionLocal, ids


def _vectors(ids):
    return {i: [float(i), 0.5] for i in ids}


def _library_file(SessionLocal, **kwargs) -> str:
    with SessionLocal() as db:
        return "".join(
            lf.library_lines(
                db,
                app_version="0.2.0",
                library_id="lib-1",
                model={"name": "small", "encoder_sha256": H, "dim": 2},
                vectors=_vectors,
                **kwargs,
            )
        )


def _read(text: str) -> list:
    return list(lf.read_lines(io.StringIO(text)))


def test_library_file_round_trips(library):
    SessionLocal, ids = library
    lines = _read(_library_file(SessionLocal))

    header = lines[0]
    assert isinstance(header, lf.Header)
    assert header.kind == "library"
    assert header.library_id == "lib-1"
    assert header.model is not None and header.model.dim == 2
    assert header.settings == {"stored_format": "webp"}
    lighting = {c.name: c for c in header.tag_categories}["lighting"]
    assert any(isinstance(v, lf.CommonValue) and v.aliases for v in lighting.common_values)

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
    assert day.subgroup == "Summer"
    assert day.grid.type == "square" and day.grid.width == 30 and day.grid.source == "user"
    assert {(t.category, t.value, t.source) for t in day.tags} == {
        ("season", "summer", "manual"),
        ("biome", "forest", "auto"),
    }
    assert day.colors == [("#2f4a1c", 31.0)]
    assert day.stored_hash == "cd" * 32  # the stored file's hash, not the upload's
    assert day.phash == -(2**63)
    assert day.storage_key == "aa" * 16 + ".webp"
    assert day.path is None
    assert day.vector is not None
    np.testing.assert_array_equal(lf.decode_vector(day.vector, 2), [float(ids["day"]), 0.5])
    night = forest.images[1]
    assert night.content_hash is None and night.pixel_hash is None  # nulls stay null

    ungrouped = {i.id: i for i in groups[2].images}
    clip = ungrouped[ids["clip"]]
    assert clip.media_type == "video"
    assert clip.storage_key is None and clip.source_file_id is not None

    all_ids = {i.id for g in groups for i in g.images}
    assert ids["waiting"] not in all_ids  # mid-import images are never exported

    (files,) = [ln for ln in lines if isinstance(ln, lf.SourceFilesLine)]
    by_key = {f.rel_key: f for f in files.source_files}
    assert (by_key["A/clip.mp4"].state, by_key["A/clip.mp4"].image_id) == ("image", ids["clip"])
    assert by_key["A/b.png"].state == "removed"
    # Its image isn't in the file: the next scan after a rebuild must import it again
    assert (by_key["A/w.jpg"].state, by_key["A/w.jpg"].image_id) == ("pending", None)


def test_an_empty_library_is_a_header_alone(tmp_db):
    _engine, SessionLocal = tmp_db
    lines = _read(_library_file(SessionLocal))
    assert [type(ln) for ln in lines] == [lf.Header]


def test_rows_at_the_edges_of_what_the_database_holds_round_trip(tmp_db):
    """Anything the API lets into the database must come back from an export: a file its
    own reader refuses would be a backup that can't be restored."""
    _engine, SessionLocal = tmp_db
    with SessionLocal() as db:
        group = ImageGroup(base_name="")
        db.add(group)
        db.flush()
        img = Image(
            filename="x" * 5_000,
            storage_key="ff" * 16 + ".png",
            name="n" * 5_000,
            group_id=group.id,
            image_type="token",
            media_type="gif",
            gridded=True,
            grid_type="Square",
            grid_width=0,
            grid_height=-4,
            grid_confidence=float("nan"),
            grid_source="manual",
        )
        db.add(img)
        db.flush()
        db.add(Tag(image_id=img.id, category="c" * 500, value="", confidence=float("inf")))
        db.add(Color(image_id=img.id, color_hex="#000000", percentage=float("nan")))
        db.commit()

    text = _library_file(SessionLocal)
    assert "NaN" not in text and "Infinity" not in text
    (line,) = [ln for ln in _read(text) if isinstance(ln, lf.GroupLine)]
    entry = line.images[0]
    assert len(entry.name or "") == 4_000  # cut short, not refused
    assert entry.image_type == "battlemap" and entry.media_type == "image"
    assert entry.grid.gridded is True
    assert entry.grid.type == "square"  # case is forgiven
    assert entry.grid.width is None and entry.grid.height is None
    assert entry.grid.confidence is None and entry.grid.source is None
    assert len(entry.tags[0].category) == 200 and entry.tags[0].confidence is None
    assert entry.colors == [("#000000", 0.0)]  # SQLite stores NaN as NULL


def test_a_row_the_reader_must_refuse_fails_the_export_naming_it(tmp_db):
    _engine, SessionLocal = tmp_db
    with SessionLocal() as db:
        img = Image(filename="x.png", storage_key="../../etc/passwd")
        db.add(img)
        db.commit()
        image_id = img.id
    with pytest.raises(lf.ExportError, match=f"Image {image_id}"):
        _library_file(SessionLocal)


def test_a_big_group_spans_lines_with_the_same_uid(tmp_db, monkeypatch):
    monkeypatch.setattr(lf, "MAX_IMAGES_PER_LINE", 2)
    _engine, SessionLocal = tmp_db
    with SessionLocal() as db:
        group = ImageGroup(base_name="Big")
        db.add(group)
        db.flush()
        images = [
            Image(filename=f"{n}.png", storage_key=f"{n}.png", group_id=group.id) for n in "abcde"
        ]
        db.add_all(images)
        db.flush()
        group.primary_image_id = images[3].id
        db.commit()

    lines = [ln for ln in _read(_library_file(SessionLocal)) if isinstance(ln, lf.GroupLine)]
    assert [len(ln.images) for ln in lines] == [2, 2, 1]
    assert len({ln.group.uid for ln in lines if ln.group}) == 1
    # The primary is an index into the line that holds it
    assert [ln.group.primary for ln in lines if ln.group] == [None, 1, None]


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
    paths = [i.path for ln in lines for i in ln.images]
    assert paths == [
        "Czepeku_Golden Forest/Czepeku_Golden Forest_Summer_Day_G30x30[forest,summer].webp",
        "Czepeku_Golden Forest/Czepeku_Golden Forest_Night_GL.png",
        "Harbour.jpg",
    ]


def test_a_selection_only_reads_the_groups_it_touches(library, query_counter):
    SessionLocal, ids = library
    with SessionLocal() as db, query_counter:
        lines = list(lf.group_lines(db, kind=lf.KIND_GROUPS, condition=Image.id == ids["inn"]))
    assert [ln.group.base_name for ln in lines if ln.group] == ["Lone Tavern"]
    assert len(query_counter.selects("variant_groups")) == 2  # the groups touched, then none left


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
        "model": {"name": "small", "dim": 2},
    }
    return json.dumps(header | changes) + "\n"


def _group(group=None, **image) -> str:
    entry = {"filename": "a.png", "image_type": "battlemap"} | image
    return json.dumps({"group": group, "images": [entry]}) + "\n"


class TestReaderRefuses:
    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("", "empty"),
            ("not json\n", "not valid JSON"),
            ("[1, 2]\n", "not a JSON object"),
            (_header(format="other"), "format"),
            (_header(version="2.0"), "version 2.0 is not supported"),
            (_header(version="١.0"), "version"),  # Arabic-Indic digit one
            (_header() + _group(storage_key="../../etc/passwd"), "storage_key"),
            (_header() + _group(storage_key="/etc/passwd"), "storage_key"),
            (_header() + _group(id=2**63), "id"),
            (_header() + _group(id=0), "id"),
            (_header() + '{"group": null, "images": [{"filename": "a", "phash": NaN}]}\n', "NaN"),
            (_header() + '{"group": null, "images": [{"id": ' + "9" * 5_000 + "}]}\n", "JSON"),
            (_header() + "[" * 100_000 + "]" * 100_000 + "\n", "JSON"),
        ],
        # Short ids: pytest puts the id in PYTEST_CURRENT_TEST, and Windows refuses an
        # environment variable over 32,767 characters
        ids=lambda value: value[:60],
    )
    def test_invalid_input(self, text, message):
        with pytest.raises(lf.FormatError, match=message):
            _read(text)

    def test_error_names_the_line(self):
        with pytest.raises(lf.FormatError) as info:
            _read(_header() + _group() + _group(id=-1))
        assert info.value.line == 3

    @pytest.mark.parametrize("as_file", [True, False])
    def test_a_line_that_is_too_long(self, monkeypatch, tmp_path, as_file):
        monkeypatch.setattr(lf, "MAX_LINE_CHARS", 100)
        if as_file:
            path = tmp_path / "f.jsonl"
            path.write_text(_header(), encoding="utf-8")
            with lf.open_file(path) as fp, pytest.raises(lf.FormatError, match="too long"):
                list(lf.read_lines(fp))
        else:
            with pytest.raises(lf.FormatError, match="too long"):
                list(lf.read_lines([_header()]))


class TestReaderForgives:
    def test_newer_minor_versions_and_unknown_lines_and_fields(self):
        text = (
            _header(version="1.7", future_field=1)
            + json.dumps({"something_new": []})
            + "\n"
            + _group(new_image_field="x")
        )
        assert [type(ln) for ln in _read(text)] == [lf.Header, lf.GroupLine]

    def test_a_primary_out_of_range_is_dropped(self):
        group = {"uid": "0" * 32, "base_name": "G", "primary": 5}
        (_, line) = _read(_header() + _group(group=group))
        assert line.group.primary is None

    def test_vectors_of_the_wrong_size_or_without_a_model_are_dropped(self):
        good = lf.encode_vector([1.0, 2.0])
        text = (
            _header()
            + _group(vector=good)
            + _group(vector=lf.encode_vector([1.0]))
            + _group(vector="!!")
        )
        vectors = [ln.images[0].vector for ln in _read(text)[1:]]
        assert vectors == [good, None, None]
        (_, line) = _read(_header(model=None) + _group(vector=good))
        assert line.images[0].vector is None

    def test_malformed_values_become_null(self):
        (_, line) = _read(
            _header()
            + _group(stored_hash="nothex", width=-1, created_at="yesterday", thumbnail_key="../x")
        )
        entry = line.images[0]
        assert entry.stored_hash is None and entry.width is None
        assert entry.created_at is None and entry.thumbnail_key is None


def test_decode_vector_checks_its_length_and_values():
    text = lf.encode_vector([1.0, 2.0, 3.0])
    np.testing.assert_array_equal(lf.decode_vector(text, 3), [1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="expected 4"):
        lf.decode_vector(text, 4)
    with pytest.raises(ValueError, match="non-finite"):
        lf.decode_vector(lf.encode_vector([1.0, float("nan")]), 2)
