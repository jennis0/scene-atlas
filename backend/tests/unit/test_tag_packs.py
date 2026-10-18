"""Unit tests for the tag pack import service."""

import json

import pytest

from backend.app.data.vocabulary import load_vocabulary
from backend.app.models.database import TagCategory
from backend.app.services.tag_packs import get_pack_status, import_tag_pack, set_installed_packs


class TestImportTagPack:
    def test_import_creates_categories_on_empty_db(self, db_session):
        """Importing a pack into an empty DB creates the categories."""
        # Clear seeded categories to simulate empty state
        db_session.query(TagCategory).delete()
        db_session.commit()

        result = import_tag_pack(db_session, "common")

        assert result["categories_created"] > 0
        assert result["tags_added"] > 0
        assert result["tags_existing"] == 0

        # Verify categories were created in DB
        cats = db_session.query(TagCategory).all()
        assert len(cats) > 0

    def test_import_is_idempotent(self, db_session):
        """Importing the same pack twice adds nothing the second time."""
        # First import (on top of seed data which already has common tags)
        import_tag_pack(db_session, "common")

        # Second import
        result2 = import_tag_pack(db_session, "common")

        assert result2["tags_added"] == 0
        assert result2["categories_created"] == 0

    def test_import_merges_new_tags(self, db_session):
        """Importing a genre pack adds new tags to existing categories."""
        # Seeded with common only; importing scifi — should add new tags
        result = import_tag_pack(db_session, "scifi")
        assert result["tags_added"] > 0

    def test_import_preserves_user_added_tags(self, db_session):
        """Importing a pack doesn't remove user-customised values."""
        # Add a custom tag to the lighting category
        cat = db_session.query(TagCategory).filter(TagCategory.name == "lighting").first()
        values = json.loads(cat.common_values or "[]")
        values.append({"value": "ultraviolet", "aliases": ["uv"]})
        cat.common_values = json.dumps(values)
        db_session.commit()

        # Import common pack
        import_tag_pack(db_session, "common")

        # Verify custom tag is still present
        cat = db_session.query(TagCategory).filter(TagCategory.name == "lighting").first()
        values = json.loads(cat.common_values)
        canonical_values = {v if isinstance(v, str) else v["value"] for v in values}
        assert "ultraviolet" in canonical_values

    def test_import_unions_aliases(self, db_session):
        """Importing a pack merges new aliases into existing tags."""
        # Modify an existing tag to have fewer aliases
        cat = db_session.query(TagCategory).filter(TagCategory.name == "weather").first()
        values = json.loads(cat.common_values or "[]")
        for v in values:
            if isinstance(v, dict) and v["value"] == "rain":
                v["aliases"] = ["rainy"]  # Remove other aliases
                break
        cat.common_values = json.dumps(values)
        db_session.commit()

        # Import common pack which has more aliases for rain
        import_tag_pack(db_session, "common")

        # Check aliases were merged
        cat = db_session.query(TagCategory).filter(TagCategory.name == "weather").first()
        values = json.loads(cat.common_values)
        for v in values:
            if isinstance(v, dict) and v["value"] == "rain":
                assert "rainy" in v["aliases"]
                assert "raining" in v["aliases"]
                break

    def test_import_invalid_pack_raises(self, db_session):
        """Importing an unknown pack name raises ValueError."""
        import pytest

        with pytest.raises(ValueError, match="nonexistent"):
            import_tag_pack(db_session, "nonexistent")


class TestGetPackStatus:
    def test_returns_all_packs(self, db_session):
        """Status includes all available packs."""
        status = get_pack_status(db_session)
        names = {p["name"] for p in status}
        assert "common" in names
        assert "fantasy" in names
        assert "scifi" in names

    def test_first_boot_seed_imports_only_common(self, db_session):
        """First-boot seeding installs the common pack; genre packs stay opt-in."""
        status = {p["name"]: p for p in get_pack_status(db_session)}
        assert status["common"]["imported"] is True
        assert status["common"]["new_tags"] == 0
        genre = [p for name, p in status.items() if name != "common"]
        assert genre
        for pack in genre:
            assert pack["imported"] is False, pack["name"]
            assert pack["new_tags"] > 0

    def test_shows_new_tags_when_pack_not_imported(self, db_session):
        """When a pack's tags are missing, new_tags shows the count."""
        # Remove all theme tags (which contain fantasy-only tags)
        cat = db_session.query(TagCategory).filter(TagCategory.name == "theme").first()
        cat.common_values = json.dumps([])
        db_session.commit()

        status = get_pack_status(db_session)
        # Fantasy pack should now show missing tags
        fantasy = next(p for p in status if p["name"] == "fantasy")
        assert fantasy["new_tags"] > 0
        assert fantasy["imported"] is False


def _installed(db_session) -> dict[str, bool]:
    return {p["name"]: p["imported"] for p in get_pack_status(db_session)}


class TestSetInstalledPacks:
    """The setup wizard's choice: exactly these packs, Common included only if chosen."""

    def test_without_common_leaves_every_category_present_but_empty(self, db_session):
        set_installed_packs(db_session, [])

        cats = {c.name: c for c in db_session.query(TagCategory).all()}
        assert set(cats) >= {c["name"] for c in load_vocabulary()["categories"]}
        assert all(json.loads(c.common_values) == [] for c in cats.values())
        assert not any(_installed(db_session).values())

    def test_installs_exactly_the_chosen_packs(self, db_session):
        set_installed_packs(db_session, ["fantasy"])

        installed = _installed(db_session)
        assert installed["fantasy"] is True
        assert installed["common"] is False
        assert installed["scifi"] is False

    def test_keeps_a_tag_shared_with_a_chosen_pack(self, db_session):
        """'portal' is in fantasy and scifi: choosing scifi alone keeps it."""
        set_installed_packs(db_session, ["scifi"])

        cat = db_session.query(TagCategory).filter(TagCategory.name == "features").one()
        values = {v if isinstance(v, str) else v["value"] for v in json.loads(cat.common_values)}
        assert "portal" in values

    def test_can_change_the_choice(self, db_session):
        set_installed_packs(db_session, ["fantasy", "horror"])
        set_installed_packs(db_session, ["common"])

        installed = _installed(db_session)
        assert installed["common"] is True
        assert installed["fantasy"] is False
        assert installed["horror"] is False

    def test_unknown_pack_changes_nothing(self, db_session):
        before = _installed(db_session)
        with pytest.raises(ValueError, match="nonexistent"):
            set_installed_packs(db_session, ["fantasy", "nonexistent"])
        assert _installed(db_session) == before
