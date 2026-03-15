"""Unit tests for the tag vocabulary loader."""

import json

from backend.app.data.vocabulary import (
    build_common_values_json,
    get_available_packs,
    get_pack_metadata,
    get_tags_for_packs,
    load_vocabulary,
)


class TestLoadVocabulary:
    def test_loads_valid_structure(self):
        vocab = load_vocabulary()
        assert "version" in vocab
        assert "packs" in vocab
        assert "categories" in vocab
        assert isinstance(vocab["categories"], list)
        assert len(vocab["categories"]) > 0

    def test_every_category_has_required_fields(self):
        vocab = load_vocabulary()
        for cat in vocab["categories"]:
            assert "name" in cat, f"Category missing name: {cat}"
            assert "description" in cat
            assert "color" in cat
            assert "display_order" in cat
            assert "tags" in cat
            assert isinstance(cat["tags"], list)
            assert len(cat["tags"]) > 0, f"Category '{cat['name']}' has no tags"

    def test_every_tag_has_required_fields(self):
        vocab = load_vocabulary()
        for cat in vocab["categories"]:
            for tag in cat["tags"]:
                assert "value" in tag, f"Tag missing value in {cat['name']}"
                assert "aliases" in tag, f"Tag '{tag['value']}' missing aliases"
                assert "packs" in tag, f"Tag '{tag['value']}' missing packs"
                assert isinstance(tag["aliases"], list)
                assert isinstance(tag["packs"], list)
                assert len(tag["packs"]) > 0, f"Tag '{tag['value']}' has no pack membership"

    def test_all_tag_packs_reference_valid_packs(self):
        vocab = load_vocabulary()
        valid_packs = set(vocab["packs"].keys())
        for cat in vocab["categories"]:
            for tag in cat["tags"]:
                for pack in tag["packs"]:
                    assert pack in valid_packs, (
                        f"Tag '{tag['value']}' references unknown pack '{pack}'"
                    )

    def test_no_duplicate_tag_values_within_category(self):
        vocab = load_vocabulary()
        for cat in vocab["categories"]:
            values = [tag["value"] for tag in cat["tags"]]
            assert len(values) == len(set(values)), (
                f"Duplicate values in '{cat['name']}': {[v for v in values if values.count(v) > 1]}"
            )

    def test_no_alias_conflicts_within_category(self):
        """No alias should duplicate another tag's canonical value or alias."""
        vocab = load_vocabulary()
        for cat in vocab["categories"]:
            all_terms: dict[str, str] = {}
            for tag in cat["tags"]:
                val = tag["value"]
                if val in all_terms:
                    raise AssertionError(
                        f"'{val}' in '{cat['name']}' conflicts with '{all_terms[val]}'"
                    )
                all_terms[val] = f"value:{val}"
                for alias in tag["aliases"]:
                    if alias in all_terms:
                        raise AssertionError(
                            f"Alias '{alias}' for '{val}' in '{cat['name']}' "
                            f"conflicts with {all_terms[alias]}"
                        )
                    all_terms[alias] = f"alias of {val}"


class TestGetPackMetadata:
    def test_returns_all_packs(self):
        meta = get_pack_metadata()
        assert "common" in meta
        assert "fantasy" in meta
        assert "scifi" in meta
        assert "cyberpunk" in meta
        assert "horror" in meta
        assert "historical" in meta

    def test_packs_have_label_and_description(self):
        meta = get_pack_metadata()
        for name, pack in meta.items():
            assert "label" in pack, f"Pack '{name}' missing label"
            assert "description" in pack, f"Pack '{name}' missing description"


class TestGetAvailablePacks:
    def test_returns_pack_names(self):
        packs = get_available_packs()
        assert isinstance(packs, list)
        assert "common" in packs
        assert len(packs) >= 6


class TestGetTagsForPacks:
    def test_common_includes_most_categories(self):
        categories = get_tags_for_packs(["common"])
        cat_names = {c["name"] for c in categories}
        # Common should include at least lighting, season, weather, environment
        assert "lighting" in cat_names
        assert "season" in cat_names
        assert "weather" in cat_names
        assert "environment" in cat_names

    def test_filters_to_specified_pack(self):
        scifi = get_tags_for_packs(["scifi"])
        for cat in scifi:
            for tag in cat["tags"]:
                assert "scifi" in tag["packs"], (
                    f"Tag '{tag['value']}' should not be in scifi results"
                )

    def test_multiple_packs_union(self):
        fantasy_only = get_tags_for_packs(["fantasy"])
        horror_only = get_tags_for_packs(["horror"])
        combined = get_tags_for_packs(["fantasy", "horror"])

        fantasy_count = sum(len(c["tags"]) for c in fantasy_only)
        horror_count = sum(len(c["tags"]) for c in horror_only)
        combined_count = sum(len(c["tags"]) for c in combined)

        # Combined should be >= max of individual (some tags in both)
        assert combined_count >= max(fantasy_count, horror_count)

    def test_empty_pack_list_returns_nothing(self):
        result = get_tags_for_packs([])
        assert result == []


class TestBuildCommonValuesJson:
    def test_plain_string_for_no_aliases(self):
        tags = [{"value": "night", "aliases": [], "packs": ["common"]}]
        result = json.loads(build_common_values_json(tags))
        assert result == ["night"]

    def test_object_for_aliases(self):
        tags = [{"value": "rain", "aliases": ["rainy", "raining"], "packs": ["common"]}]
        result = json.loads(build_common_values_json(tags))
        assert result == [{"value": "rain", "aliases": ["rainy", "raining"]}]

    def test_mixed_entries(self):
        tags = [
            {"value": "night", "aliases": [], "packs": ["common"]},
            {"value": "rain", "aliases": ["rainy"], "packs": ["common"]},
            {"value": "dusk", "aliases": [], "packs": ["common"]},
        ]
        result = json.loads(build_common_values_json(tags))
        assert result == [
            "night",
            {"value": "rain", "aliases": ["rainy"]},
            "dusk",
        ]
