"""Tests for staging directory helpers."""

from backend.app.services.staging import FILE_MAP_NAME, load_file_map, save_file_map


def test_file_map_name_constant():
    assert FILE_MAP_NAME == ".file_map.json"


def test_round_trip(tmp_path):
    mapping = {"images/a.jpg": "key-abc", "images/b.png": "key-def"}
    save_file_map(tmp_path, mapping)
    assert (tmp_path / FILE_MAP_NAME).exists()
    result = load_file_map(tmp_path)
    assert result == mapping


def test_load_missing_returns_empty(tmp_path):
    assert load_file_map(tmp_path) == {}


def test_save_overwrites_existing(tmp_path):
    save_file_map(tmp_path, {"old": "value"})
    save_file_map(tmp_path, {"new": "value"})
    assert load_file_map(tmp_path) == {"new": "value"}
