# Split Storage, WebP Conversion & Setup Wizard — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single `DATA_DIR` config with separate fast-storage (`APP_DATA_DIR`) and cold-storage (`IMAGE_LIBRARY_DIR`) roots, add lossless WebP conversion on import, and update the Electron setup wizard + settings UI to configure all three options.

**Architecture:** The `Settings` class in `config.py` is refactored to derive all paths from two independent roots instead of one. WebP conversion is a new isolated module called from `prepare_single_image` before the image is copied to the store. All Electron IPC channels, the setup wizard HTML, and the React settings panel are updated to expose the new configuration.

**Tech Stack:** Python/Pydantic-Settings, Pillow (WebP via built-in support), TypeScript/Electron IPC, React + Tailwind, pytest/monkeypatch.

**Spec:** `design/2026-03-15-split-storage-webp-setup-design.md`

---

## Chunk 1: Backend Config Split + WebP Schema

Files:
- Modify: `backend/app/config.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/models/database.py` (`seed_default_settings` around line 614)
- Modify: `backend/pyinstaller/entry.py`
- Create: `backend/tests/unit/test_config_roots.py`
- Create: `backend/tests/unit/test_settings_seed.py`

---

### Task 1.1: Rewrite `Settings` for two roots

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Read the current config**

  Read `backend/app/config.py` in full before changing anything.

- [ ] **Step 2: Write failing tests first**

  Create `backend/tests/unit/test_config_roots.py`:

  ```python
  """Tests for two-root config split (APP_DATA_DIR + IMAGE_LIBRARY_DIR)."""
  from pathlib import Path
  import pytest
  from backend.app.config import Settings


  class TestConfigDefaults:
      def test_both_roots_accepted_as_kwargs(self, tmp_path):
          (tmp_path / "data").mkdir()
          (tmp_path / "images").mkdir()
          s = Settings(app_data_dir=tmp_path / "data", image_library_dir=tmp_path / "images")
          assert s.app_data_dir == tmp_path / "data"
          assert s.image_library_dir == tmp_path / "images"

      def test_derived_paths_from_app_data_dir(self, tmp_path):
          (tmp_path / "data").mkdir()
          (tmp_path / "images").mkdir()
          s = Settings(app_data_dir=tmp_path / "data", image_library_dir=tmp_path / "images")
          assert s.store_thumbnails_dir == tmp_path / "data" / "store" / "thumbnails"
          assert s.staging_dir == tmp_path / "data" / "staging"
          assert s.qdrant_path == tmp_path / "data" / "qdrant_local"
          assert s.config_dir == tmp_path / "data" / "config"

      def test_image_store_is_flat_under_image_library(self, tmp_path):
          (tmp_path / "data").mkdir()
          (tmp_path / "images").mkdir()
          s = Settings(app_data_dir=tmp_path / "data", image_library_dir=tmp_path / "images")
          assert s.store_images_dir == tmp_path / "images"

      def test_backups_under_image_library(self, tmp_path):
          (tmp_path / "data").mkdir()
          (tmp_path / "images").mkdir()
          s = Settings(app_data_dir=tmp_path / "data", image_library_dir=tmp_path / "images")
          assert s.backups_dir == tmp_path / "images" / "backups"

      def test_env_override_recomputes_derived_paths(self, monkeypatch, tmp_path):
          (tmp_path / "fast").mkdir()
          (tmp_path / "slow").mkdir()
          monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "fast"))
          monkeypatch.setenv("IMAGE_LIBRARY_DIR", str(tmp_path / "slow"))
          s = Settings()
          assert s.store_thumbnails_dir == tmp_path / "fast" / "store" / "thumbnails"
          assert s.store_images_dir == tmp_path / "slow"
          assert s.backups_dir == tmp_path / "slow" / "backups"

      def test_database_url_uses_app_data_dir(self, tmp_path):
          (tmp_path / "data").mkdir()
          (tmp_path / "images").mkdir()
          s = Settings(app_data_dir=tmp_path / "data", image_library_dir=tmp_path / "images")
          assert str(tmp_path / "data" / "battlemap.db") in s.database_url


  class TestStartupValidation:
      def test_raises_if_app_data_dir_missing(self, tmp_path):
          (tmp_path / "images").mkdir()
          with pytest.raises(ValueError, match="APP_DATA_DIR"):
              Settings(
                  app_data_dir=tmp_path / "nonexistent",
                  image_library_dir=tmp_path / "images",
                  validate_roots=True,
              )

      def test_raises_if_image_library_dir_missing(self, tmp_path):
          (tmp_path / "data").mkdir()
          with pytest.raises(ValueError, match="IMAGE_LIBRARY_DIR"):
              Settings(
                  app_data_dir=tmp_path / "data",
                  image_library_dir=tmp_path / "nonexistent",
                  validate_roots=True,
              )

      def test_no_raise_when_roots_exist(self, tmp_path):
          (tmp_path / "data").mkdir()
          (tmp_path / "images").mkdir()
          # Should not raise
          Settings(
              app_data_dir=tmp_path / "data",
              image_library_dir=tmp_path / "images",
              validate_roots=True,
          )

      def test_subdirs_created_within_roots(self, tmp_path):
          (tmp_path / "data").mkdir()
          (tmp_path / "images").mkdir()
          s = Settings(app_data_dir=tmp_path / "data", image_library_dir=tmp_path / "images")
          assert s.store_thumbnails_dir.exists()
          assert s.staging_dir.exists()
          assert s.qdrant_path.exists()
          assert s.config_dir.exists()
  ```

- [ ] **Step 3: Run tests to confirm they fail**

  ```bash
  cd /home/joe/code/scene-atlas
  uv run pytest backend/tests/unit/test_config_roots.py -v
  ```
  Expected: `AttributeError` — `app_data_dir`, `image_library_dir`, `validate_roots` don't exist yet.

- [ ] **Step 4: Rewrite `backend/app/config.py`**

  Replace the full class body. Key design decisions:
  - `validate_roots: bool = False` is a **public** Pydantic field (no leading underscore — private attrs can't be passed as constructor kwargs in Pydantic v2).
  - `database_url` is a `@property` (removed as a plain field).
  - `__init__` **unconditionally** recomputes all derived paths from `app_data_dir` and `image_library_dir` — no conditional equality check against defaults. This is simpler and correct.
  - `backups_dir` is new, derived from `image_library_dir`.
  - `config_dir` moves from `base_dir/config` to `app_data_dir/config`.

  ```python
  """Application configuration management."""

  import logging
  import os
  from pathlib import Path
  from typing import Literal

  from pydantic_settings import BaseSettings, SettingsConfigDict


  class Settings(BaseSettings):
      """Application settings."""

      model_config = SettingsConfigDict(
          env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
      )

      # Application
      app_name: str = "Scene Atlas"
      app_version: str = "0.1.0"
      debug: bool = False

      # Deployment mode: 'app' when running as Electron desktop sidecar,
      # 'server' when running standalone via uvicorn.  Set via APP_MODE env var.
      app_mode: Literal["app", "server"] = "server"

      # Storage roots — set via APP_DATA_DIR and IMAGE_LIBRARY_DIR env vars
      app_data_dir: Path = Path(__file__).parent.parent.parent / "data"
      image_library_dir: Path = Path(__file__).parent.parent.parent / "images"

      # Whether to validate that roots exist on startup.
      # Set to True in production entry points (entry.py).  False by default so
      # that tests and dev runs don't require pre-created directories.
      validate_roots: bool = False

      # Derived paths — recomputed unconditionally in __init__ from the roots above.
      # Declared here as fields so type-checkers and callers can read them as attributes.
      store_thumbnails_dir: Path = Path(__file__).parent.parent.parent / "data" / "store" / "thumbnails"
      staging_dir: Path = Path(__file__).parent.parent.parent / "data" / "staging"
      qdrant_path: Path = Path(__file__).parent.parent.parent / "data" / "qdrant_local"
      config_dir: Path = Path(__file__).parent.parent.parent / "data" / "config"
      store_images_dir: Path = Path(__file__).parent.parent.parent / "images"
      backups_dir: Path = Path(__file__).parent.parent.parent / "images" / "backups"

      # Qdrant
      qdrant_vector_size: int = 512
      embedding_model: str = "clip-vit-b-32"
      inference_device: str = "auto"

      @property
      def qdrant_collection_name(self) -> str:
          return f"embeddings_{self.embedding_model}"

      # database_url is computed from app_data_dir in __init__.
      # Declared as a plain field (not @property) so that test fixtures can
      # assign settings.database_url = str(engine.url) without AttributeError.
      database_url: str = ""

      # ── Service constants ──────────────────────────────────────────────────────
      clip_text_cache_max: int = 256
      color_cache_ttl_seconds: float = 60.0
      job_retention_seconds: int = 3600

      # Image Processing
      thumbnail_sizes: list[tuple[int, int]] = [(150, 150), (400, 400), (800, 800)]
      max_image_size: int = 10 * 1024 * 1024
      supported_formats: list[str] = [".jpg", ".jpeg", ".png", ".webp"]
      supported_video_formats: list[str] = [".mp4", ".webm"]

      @property
      def all_supported_formats(self) -> list[str]:
          return self.supported_formats + self.supported_video_formats

      # Rate limiting
      rate_limit_expensive: str = "2/minute"
      rate_limit_destructive: str = "1/minute"
      rate_limit_enabled: bool = True

      # API
      api_host: str = "0.0.0.0"
      api_port: int = 8000
      api_prefix: str = "/api/v1"
      cors_origins: list[str] = [
          "http://localhost:3000",
          "http://localhost:5173",
          "http://localhost:8000",
      ]

      def __init__(self, **kwargs):
          super().__init__(**kwargs)

          # Migration aid: warn if the old CLIP_DEVICE env var is set
          if os.environ.get("CLIP_DEVICE"):
              logging.getLogger(__name__).warning(
                  "CLIP_DEVICE env var is deprecated and ignored. "
                  "Use INFERENCE_DEVICE instead (auto/cpu/cuda/directml/coreml)."
              )

          # Unconditionally recompute all derived paths from the roots.
          # Class-level field defaults are computed at class-definition time using
          # literal Path(__file__) chains and will NOT reflect overridden root values.
          self.store_thumbnails_dir = self.app_data_dir / "store" / "thumbnails"
          self.staging_dir = self.app_data_dir / "staging"
          self.qdrant_path = self.app_data_dir / "qdrant_local"
          self.config_dir = self.app_data_dir / "config"
          self.store_images_dir = self.image_library_dir
          self.backups_dir = self.image_library_dir / "backups"
          self.database_url = f"sqlite:///{self.app_data_dir / 'battlemap.db'}"

          # Validate roots exist if requested (set True in production entry points)
          if self.validate_roots:
              if not self.app_data_dir.exists():
                  raise ValueError(
                      f"APP_DATA_DIR does not exist: {self.app_data_dir}. "
                      "Create it before starting the backend."
                  )
              if not self.image_library_dir.exists():
                  raise ValueError(
                      f"IMAGE_LIBRARY_DIR does not exist: {self.image_library_dir}. "
                      "Create it before starting the backend."
                  )

          # Create expected subdirectories within the roots (not the roots themselves).
          self.store_thumbnails_dir.mkdir(parents=True, exist_ok=True)
          self.staging_dir.mkdir(parents=True, exist_ok=True)
          self.config_dir.mkdir(parents=True, exist_ok=True)
          self.qdrant_path.mkdir(parents=True, exist_ok=True)


  # Global settings instance
  settings = Settings()
  ```

- [ ] **Step 5: Grep for stale `data_dir` references that now need updating**

  ```bash
  grep -rn "settings\.data_dir\|DATA_DIR\b\|settings\.base_dir\|settings\.db_path" /home/joe/code/scene-atlas/backend --include="*.py" | grep -v "__pycache__" | grep -v "test_config"
  ```
  Fix any occurrences found. There should be none beyond the config and entry files, but also check for `base_dir` and `db_path` which are removed by this refactor.

- [ ] **Step 6: Run tests**

  ```bash
  uv run pytest backend/tests/unit/test_config_roots.py -v
  ```
  Expected: all PASS.

- [ ] **Step 7: Run the full test suite**

  ```bash
  uv run pytest backend/tests/ -x -q
  ```
  Expected: all PASS (or pre-existing failures only). Fix regressions before proceeding.

- [ ] **Step 8: Commit**

  ```bash
  git add backend/app/config.py backend/tests/unit/test_config_roots.py
  git commit -m "refactor(config): split DATA_DIR into APP_DATA_DIR + IMAGE_LIBRARY_DIR"
  ```

---

### Task 1.2: Add WebP fields to AppSettings schema + seed

**Files:**
- Modify: `backend/app/models/schemas.py` (class `AppSettings` at line 537, class `AppSettingsPatch` at line 576)
- Modify: `backend/app/models/database.py` (`seed_default_settings` at line 614)
- Create: `backend/tests/unit/test_settings_seed.py`

- [ ] **Step 1: Add fields to `AppSettings` in `schemas.py`**

  In `AppSettings` (around line 573, after `scheduler_enabled`), add:

  ```python
  # Import processing
  convert_to_webp: bool = True
  webp_lossless: bool = True
  webp_quality: int = 95
  ```

- [ ] **Step 2: Add fields to `AppSettingsPatch` in `schemas.py`**

  In `AppSettingsPatch` (after `scheduler_enabled: bool | None = None`), add:

  ```python
  convert_to_webp: bool | None = None
  webp_lossless: bool | None = None
  webp_quality: int | None = None
  ```

- [ ] **Step 3: Add `import os` and WebP keys to `seed_default_settings` in `database.py`**

  Add `import os` at the top of `database.py` (it is not currently imported). Then in `seed_default_settings`, add after `"scheduler_enabled": True`:

  ```python
  # Import processing — initial value read from env so setup wizard choice is honoured
  "convert_to_webp": bool(int(os.environ.get("CONVERT_TO_WEBP", "1"))),
  "webp_lossless": True,
  "webp_quality": 95,
  ```

- [ ] **Step 4: Write tests for the seeding logic**

  Create `backend/tests/unit/test_settings_seed.py`:

  ```python
  """Tests for seed_default_settings WebP env var handling."""
  import json
  import os
  import pytest
  from unittest.mock import patch
  from sqlalchemy import create_engine
  from sqlalchemy.orm import sessionmaker
  from backend.app.models.database import Base, AppSetting, seed_default_settings


  @pytest.fixture
  def fresh_db():
      engine = create_engine("sqlite:///:memory:")
      Base.metadata.create_all(engine)
      Session = sessionmaker(bind=engine)
      db = Session()
      yield db
      db.close()


  class TestWebPSeed:
      def test_convert_to_webp_defaults_true(self, fresh_db):
          with patch.dict(os.environ, {}, clear=False):
              os.environ.pop("CONVERT_TO_WEBP", None)
              seed_default_settings(fresh_db)
          row = fresh_db.query(AppSetting).filter_by(key="convert_to_webp").first()
          assert row is not None
          assert json.loads(row.value_json) is True

      def test_convert_to_webp_false_from_env(self, fresh_db):
          with patch.dict(os.environ, {"CONVERT_TO_WEBP": "0"}):
              seed_default_settings(fresh_db)
          row = fresh_db.query(AppSetting).filter_by(key="convert_to_webp").first()
          assert json.loads(row.value_json) is False

      def test_convert_to_webp_true_from_env(self, fresh_db):
          with patch.dict(os.environ, {"CONVERT_TO_WEBP": "1"}):
              seed_default_settings(fresh_db)
          row = fresh_db.query(AppSetting).filter_by(key="convert_to_webp").first()
          assert json.loads(row.value_json) is True

      def test_seed_is_noop_if_rows_exist(self, fresh_db):
          # Pre-populate — seed should be a no-op and must not overwrite existing values
          fresh_db.add(AppSetting(key="convert_to_webp", value_json="false"))
          fresh_db.commit()
          seed_default_settings(fresh_db)
          count = fresh_db.query(AppSetting).count()
          assert count == 1
          row = fresh_db.query(AppSetting).filter_by(key="convert_to_webp").first()
          assert json.loads(row.value_json) is False, "seed must not overwrite existing values"
  ```

- [ ] **Step 5: Run the new tests**

  ```bash
  uv run pytest backend/tests/unit/test_settings_seed.py -v
  ```
  Expected: all PASS.

- [ ] **Step 6: Run full suite**

  ```bash
  uv run pytest backend/tests/ -x -q
  ```

- [ ] **Step 7: Commit**

  ```bash
  git add backend/app/models/schemas.py backend/app/models/database.py backend/tests/unit/test_settings_seed.py
  git commit -m "feat(settings): add convert_to_webp / webp_lossless / webp_quality app settings"
  ```

---

### Task 1.3: Update PyInstaller entry point

**Files:**
- Modify: `backend/pyinstaller/entry.py`

- [ ] **Step 1: Read the current `entry.py`** in full.

- [ ] **Step 2: Update CLI argument parsing and env var setup**

  Replace the `--data-dir` argument with two new args, update env vars, update logging path, and add a root-existence check:

  ```python
  def main():
      parser = argparse.ArgumentParser(description="Scene Atlas backend (packaged)")
      parser.add_argument("--port", type=int, required=True, help="Port to bind to")
      parser.add_argument("--app-data-dir", type=str, required=True,
                          help="App data directory (fast storage: DB, index, thumbnails)")
      parser.add_argument("--image-library-dir", type=str, required=True,
                          help="Image library directory (cold storage: originals, backups)")
      args = parser.parse_args()

      # Validate roots exist before importing any backend modules.
      # (Settings.__init__ also validates when validate_roots=True, but we
      # check here first so the error appears before any heavy imports.)
      from pathlib import Path
      for label, dirpath in [
          ("APP_DATA_DIR", args.app_data_dir),
          ("IMAGE_LIBRARY_DIR", args.image_library_dir),
      ]:
          if not Path(dirpath).exists():
              print(f"ERROR: {label} does not exist: {dirpath}", file=sys.stderr)
              sys.exit(1)

      # Must set env vars before any backend.app import triggers Settings()
      os.environ["APP_DATA_DIR"] = args.app_data_dir
      os.environ["IMAGE_LIBRARY_DIR"] = args.image_library_dir
      os.environ["VALIDATE_ROOTS"] = "1"  # Settings() will raise if roots don't exist
      os.environ["API_PORT"] = str(args.port)
      os.environ["API_HOST"] = "127.0.0.1"
      os.environ["APP_MODE"] = "app"

      from backend.app.logging_config import setup_logging
      setup_logging(Path(args.app_data_dir))

      # ... rest of the function unchanged (uvicorn.run loop)
  ```

- [ ] **Step 3: Verify no stale `data_dir` references remain**

  ```bash
  grep -n "data.dir\|DATA_DIR" /home/joe/code/scene-atlas/backend/pyinstaller/entry.py
  ```
  Expected: only the new `APP_DATA_DIR` / `IMAGE_LIBRARY_DIR` references.

- [ ] **Step 4: Commit**

  ```bash
  git add backend/pyinstaller/entry.py
  git commit -m "feat(sidecar): update entry point for --app-data-dir / --image-library-dir args"
  ```

---

## Chunk 2: WebP Conversion Pipeline

**Chunk 1 must be complete before starting Chunk 2** (`PipelineConfig.use_webp` maps from `AppSettings.convert_to_webp` which is added in Chunk 1).

Files:
- Create: `backend/pipeline/tasks/webp_conversion.py`
- Create: `backend/tests/unit/test_webp_conversion.py`
- Create: `backend/tests/unit/test_image_processing.py`
- Modify: `backend/pipeline/pipeline_config.py`
- Modify: `backend/pipeline/tasks/image_processing.py`
- Modify: `backend/pipeline/prepare.py`

---

### Task 2.1: WebP conversion module

**Files:**
- Create: `backend/pipeline/tasks/webp_conversion.py`
- Create: `backend/tests/unit/test_webp_conversion.py`

- [ ] **Step 1: Write failing tests**

  Create `backend/tests/unit/test_webp_conversion.py`:

  ```python
  """Unit tests for WebP conversion helper."""
  from pathlib import Path
  import pytest
  from PIL import Image as PILImage
  from backend.pipeline.tasks.webp_conversion import convert_to_webp, should_skip_conversion


  def make_image(tmp_path, mode="RGB", ext=".png", filename=None) -> Path:
      """Create a minimal test image on disk."""
      name = filename or f"test{ext}"
      path = tmp_path / name
      img = PILImage.new(mode, (4, 4), 0)
      img.save(str(path))
      return path


  def make_animated_gif(tmp_path) -> Path:
      path = tmp_path / "animated.gif"
      frames = [PILImage.new("P", (4, 4), i) for i in range(2)]
      frames[0].save(str(path), save_all=True, append_images=frames[1:], loop=0)
      return path


  class TestShouldSkipConversion:
      def test_skip_video_mp4(self):
          assert should_skip_conversion(Path("clip.mp4")) is True

      def test_skip_video_webm(self):
          assert should_skip_conversion(Path("clip.webm")) is True

      def test_skip_already_webp(self):
          assert should_skip_conversion(Path("img.webp")) is True

      def test_skip_animated_gif(self, tmp_path):
          gif = make_animated_gif(tmp_path)
          assert should_skip_conversion(gif) is True

      def test_no_skip_static_gif(self, tmp_path):
          path = tmp_path / "static.gif"
          PILImage.new("P", (4, 4), 0).save(str(path))
          assert should_skip_conversion(path) is False

      def test_no_skip_png(self, tmp_path):
          p = make_image(tmp_path)
          assert should_skip_conversion(p) is False

      def test_no_skip_jpeg(self, tmp_path):
          p = tmp_path / "img.jpg"
          PILImage.new("RGB", (4, 4)).save(str(p), format="JPEG")
          assert should_skip_conversion(p) is False


  class TestConvertToWebP:
      def test_rgb_png_converts(self, tmp_path):
          src = make_image(tmp_path, mode="RGB")
          result = convert_to_webp(src)
          assert result.suffix == ".webp"
          assert result.exists()
          with PILImage.open(result) as img:
              assert img.format == "WEBP"

      def test_rgba_preserves_alpha(self, tmp_path):
          src = make_image(tmp_path, mode="RGBA", ext=".png")
          result = convert_to_webp(src)
          with PILImage.open(result) as img:
              assert img.mode == "RGBA"

      def test_palette_with_transparency_becomes_rgba(self, tmp_path):
          img = PILImage.new("P", (4, 4), 0)
          img.info["transparency"] = 0
          src = tmp_path / "palette_trans.png"
          img.save(str(src))
          result = convert_to_webp(src)
          with PILImage.open(result) as out:
              assert out.mode == "RGBA"

      def test_palette_without_transparency_becomes_rgb(self, tmp_path):
          img = PILImage.new("P", (4, 4), 0)
          src = tmp_path / "palette.png"
          img.save(str(src))
          result = convert_to_webp(src)
          with PILImage.open(result) as out:
              assert out.mode == "RGB"

      def test_original_deleted_after_conversion(self, tmp_path):
          src = make_image(tmp_path)
          result = convert_to_webp(src)
          assert not src.exists()
          assert result.exists()

      def test_video_returned_unchanged(self, tmp_path):
          mp4 = tmp_path / "clip.mp4"
          mp4.write_bytes(b"fake")
          result = convert_to_webp(mp4)
          assert result == mp4
          assert mp4.exists()

      def test_already_webp_returned_unchanged(self, tmp_path):
          p = tmp_path / "img.webp"
          PILImage.new("RGB", (4, 4)).save(str(p), format="WEBP")
          result = convert_to_webp(p)
          assert result == p
          assert p.exists()

      def test_la_mode_becomes_rgba(self, tmp_path):
          # LA (greyscale+alpha) is converted to RGBA — WebP has no LA mode
          img = PILImage.new("LA", (4, 4), (128, 200))
          src = tmp_path / "la.png"
          img.save(str(src))
          result = convert_to_webp(src)
          with PILImage.open(result) as out:
              assert out.mode == "RGBA"

      def test_cmyk_becomes_rgb(self, tmp_path):
          img = PILImage.new("CMYK", (4, 4), (0, 0, 0, 0))
          src = tmp_path / "cmyk.jpg"
          img.save(str(src), format="JPEG")
          result = convert_to_webp(src)
          with PILImage.open(result) as out:
              assert out.mode == "RGB"
  ```

- [ ] **Step 2: Run tests to confirm failure**

  ```bash
  uv run pytest backend/tests/unit/test_webp_conversion.py -v
  ```
  Expected: `ModuleNotFoundError: backend.pipeline.tasks.webp_conversion`

- [ ] **Step 3: Implement `webp_conversion.py`**

  Create `backend/pipeline/tasks/webp_conversion.py`:

  ```python
  """WebP conversion helper for the import pipeline.

  Converts a staged image file to WebP in-place (original is deleted).
  Returns the new file path, or the original path unchanged if conversion
  is skipped (video, already-WebP, animated GIF).
  """

  import logging
  from pathlib import Path

  from PIL import Image

  logger = logging.getLogger(__name__)

  _VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi"}


  def should_skip_conversion(path: Path) -> bool:
      """Return True if WebP conversion should be skipped for this file.

      Skips: videos (by extension), files already in WebP format, animated GIFs.
      """
      ext = path.suffix.lower()
      if ext in _VIDEO_EXTENSIONS:
          return True
      if ext == ".webp":
          return True
      if ext == ".gif":
          try:
              with Image.open(path) as img:
                  return getattr(img, "n_frames", 1) > 1
          except Exception:
              return True  # Can't open — skip safely
      return False


  def _prepare_mode(img: Image.Image) -> Image.Image:
      """Convert image to a mode compatible with WebP encoding."""
      mode = img.mode
      if mode == "P":
          has_transparency = "transparency" in img.info
          return img.convert("RGBA" if has_transparency else "RGB")
      if mode == "CMYK":
          return img.convert("RGB")
      if mode == "RGBA":
          return img  # Preserve alpha as-is
      if mode == "LA":
          return img.convert("RGBA")  # Pillow WebP encoder has no LA mode; RGBA preserves alpha
      if mode != "RGB":
          return img.convert("RGB")
      return img


  def convert_to_webp(path: Path, lossless: bool = True, method: int = 4) -> Path:
      """Convert image at *path* to WebP, returning the new file path.

      If conversion is skipped (video / already-WebP / animated GIF), the
      original *path* is returned unchanged and no files are modified.

      Otherwise:
      - Converts and saves as ``<stem>.webp`` in the same directory.
      - Deletes the original file.
      - Returns the new ``.webp`` path.

      Args:
          path: Absolute path to the source image.
          lossless: Use lossless WebP encoding (default: True).
          method: Pillow WebP encode method 0–6; 4 balances speed and compression.
      """
      if should_skip_conversion(path):
          return path

      webp_path = path.with_suffix(".webp")

      try:
          with Image.open(path) as img:
              converted = _prepare_mode(img)
              converted.save(str(webp_path), format="WEBP", lossless=lossless, method=method)
              if converted is not img:
                  converted.close()

          path.unlink()  # Delete original after successful save
          logger.debug("Converted %s → %s", path.name, webp_path.name)
          return webp_path

      except Exception:
          logger.exception("WebP conversion failed for %s — keeping original", path)
          if webp_path.exists():
              webp_path.unlink()
          return path  # Fall through with original on failure
  ```

- [ ] **Step 4: Run tests**

  ```bash
  uv run pytest backend/tests/unit/test_webp_conversion.py -v
  ```
  Expected: all PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/pipeline/tasks/webp_conversion.py backend/tests/unit/test_webp_conversion.py
  git commit -m "feat(pipeline): add WebP conversion module with full mode handling"
  ```

---

### Task 2.2: Add `use_webp` to PipelineConfig and thumbnail generation

**Files:**
- Modify: `backend/pipeline/pipeline_config.py`
- Modify: `backend/pipeline/tasks/image_processing.py`
- Create: `backend/tests/unit/test_image_processing.py`

- [ ] **Step 1: Write failing tests for thumbnail WebP output**

  Create `backend/tests/unit/test_image_processing.py`:

  ```python
  """Tests for generate_thumbnails use_webp parameter."""
  import pytest
  from pathlib import Path
  from PIL import Image as PILImage
  from backend.pipeline.tasks.image_processing import generate_thumbnails


  @pytest.fixture
  def sample_image(tmp_path) -> str:
      p = tmp_path / "sample.jpg"
      PILImage.new("RGB", (800, 600), color=(100, 150, 200)).save(str(p), format="JPEG")
      return str(p)


  @pytest.fixture
  def mock_thumb_store(tmp_path, monkeypatch):
      from backend.app.services.image_store import ImageStore
      store = ImageStore(tmp_path / "thumbs")
      monkeypatch.setattr(
          "backend.pipeline.tasks.image_processing.get_thumbnail_store",
          lambda: store,
      )
      return store


  class TestThumbnailFormat:
      def test_jpeg_by_default(self, sample_image, mock_thumb_store):
          result = generate_thumbnails(sample_image, "abc123", use_webp=False)
          for key in result["keys"].values():
              assert key.endswith(".jpg"), f"Expected .jpg key, got {key}"

      def test_webp_when_flag_set(self, sample_image, mock_thumb_store):
          result = generate_thumbnails(sample_image, "abc123", use_webp=True)
          for key in result["keys"].values():
              assert key.endswith(".webp"), f"Expected .webp key, got {key}"

      def test_webp_files_are_actually_webp_format(self, sample_image, mock_thumb_store):
          result = generate_thumbnails(sample_image, "abc123", use_webp=True)
          for key in result["keys"].values():
              path = mock_thumb_store.get_path(key)
              with PILImage.open(path) as img:
                  assert img.format == "WEBP", f"File at {path} is not WebP"

      def test_dimensions_returned_correctly(self, sample_image, mock_thumb_store):
          result = generate_thumbnails(sample_image, "abc123", use_webp=False)
          width, height = result["dimensions"]
          assert width == 800
          assert height == 600

      def test_rgba_image_thumbnails_preserve_alpha(self, tmp_path, mock_thumb_store):
          rgba_img = tmp_path / "rgba.png"
          PILImage.new("RGBA", (100, 100), (50, 100, 150, 200)).save(str(rgba_img))
          result = generate_thumbnails(str(rgba_img), "def456", use_webp=True)
          for key in result["keys"].values():
              path = mock_thumb_store.get_path(key)
              with PILImage.open(path) as img:
                  assert img.mode == "RGBA"
  ```

- [ ] **Step 2: Run to confirm failure**

  ```bash
  uv run pytest backend/tests/unit/test_image_processing.py -v
  ```
  Expected: `TypeError` — `generate_thumbnails` doesn't accept `use_webp`.

- [ ] **Step 3: Update `generate_thumbnails` in `image_processing.py`**

  Read the full `backend/pipeline/tasks/image_processing.py` first. Then replace the `generate_thumbnails` function:

  ```python
  def generate_thumbnails(image_path: str, storage_key_stem: str, use_webp: bool = False) -> dict:
      """Generate thumbnails at different sizes and store via ImageStore.

      Also returns original image dimensions to avoid a separate PIL open.

      Args:
          image_path: Path to the original image file (as string for serialization)
          storage_key_stem: UUID stem for naming thumbnails (e.g., "a1b2c3d4e5f6")
          use_webp: If True, save thumbnails as WebP instead of JPEG.

      Returns:
          Dict with 'keys' (size name -> storage key) and 'dimensions' (width, height)
      """
      logger = logging.getLogger(__name__)
      try:
          image_path_obj = Path(image_path)
          thumbnail_store = get_thumbnail_store()
          thumbnail_keys = {}
          ext = "webp" if use_webp else "jpg"

          with Image.open(image_path_obj) as orig:
              # Mode conversion for thumbnail generation.
              # For WebP: preserve RGBA/LA alpha; convert palette and other modes.
              # For JPEG: always convert to RGB (JPEG has no alpha).
              if use_webp:
                  if orig.mode == "P":
                      image = orig.convert("RGBA" if "transparency" in orig.info else "RGB")
                  elif orig.mode in ("RGBA", "LA"):
                      image = orig  # keep alpha
                  elif orig.mode != "RGB":
                      image = orig.convert("RGB")
                  else:
                      image = orig
              else:
                  image = orig.convert("RGB")

              dimensions = image.size  # (width, height) — capture before thumbnailing

              for idx, (width, height) in enumerate(settings.thumbnail_sizes):
                  thumb_key = f"{storage_key_stem}_{width}x{height}.{ext}"
                  thumb_path = thumbnail_store.get_path(thumb_key)
                  thumb_path.parent.mkdir(parents=True, exist_ok=True)

                  thumb = image.copy()
                  thumb.thumbnail((width, height), Image.Resampling.LANCZOS)

                  if use_webp:
                      thumb.save(thumb_path, format="WEBP", lossless=False, quality=90)
                  else:
                      thumb.save(thumb_path, quality=85, optimize=True)
                  thumb.close()

                  size_name = ["small", "medium", "large"][idx] if idx < 3 else f"size_{idx}"
                  thumbnail_keys[size_name] = thumb_key
                  logger.debug("Generated %s thumbnail: %s", size_name, thumb_key)

              # Close the converted image if it's a different object from orig
              if image is not orig:
                  image.close()

          return {"keys": thumbnail_keys, "dimensions": dimensions}

      except Exception as e:
          logger.error("Error generating thumbnails for %s: %s", image_path, e)
          raise
  ```

- [ ] **Step 4: Run tests**

  ```bash
  uv run pytest backend/tests/unit/test_image_processing.py -v
  ```
  Expected: all PASS.

- [ ] **Step 5: Add `use_webp` to `PipelineConfig`**

  In `backend/pipeline/pipeline_config.py`, add to the `PipelineConfig` dataclass (after `max_concurrent_prepare`):

  ```python
  # Import processing
  use_webp: bool = False
  ```

  In `from_app_settings`, add to the `cls(...)` call:

  ```python
  use_webp=s.convert_to_webp,
  ```

- [ ] **Step 6: Run full suite**

  ```bash
  uv run pytest backend/tests/ -x -q
  ```
  Expected: all PASS.

- [ ] **Step 7: Commit**

  ```bash
  git add backend/pipeline/pipeline_config.py \
          backend/pipeline/tasks/image_processing.py \
          backend/tests/unit/test_image_processing.py
  git commit -m "feat(pipeline): add use_webp to PipelineConfig and generate_thumbnails"
  ```

---

### Task 2.3: Wire WebP conversion into `prepare_single_image`

**Files:**
- Modify: `backend/pipeline/prepare.py`

- [ ] **Step 1: Write integration tests**

  Add to `backend/tests/unit/test_webp_conversion.py`:

  ```python
  """Integration: prepare_single_image with use_webp=True."""
  import hashlib
  from unittest.mock import patch
  from PIL import Image as PILImage
  from backend.pipeline.pipeline_config import PipelineConfig


  @pytest.fixture
  def webp_cfg():
      return PipelineConfig(use_webp=True, enable_image_grid_detection=False)


  class TestPrepareWithWebP:
      def test_stored_key_ends_in_webp(self, tmp_path, webp_cfg):
          from backend.pipeline.prepare import prepare_single_image
          from backend.app.services.image_store import ImageStore

          src = tmp_path / "map.png"
          PILImage.new("RGB", (100, 80)).save(str(src))

          image_store = ImageStore(tmp_path / "store")
          thumb_store = ImageStore(tmp_path / "thumbs")

          with patch("backend.pipeline.prepare.get_image_store", return_value=image_store), \
               patch("backend.pipeline.tasks.image_processing.get_thumbnail_store", return_value=thumb_store), \
               patch("backend.pipeline.prepare.pipeline_db"):
              result = prepare_single_image(
                  str(src),
                  metadata={
                      "group_name": "Test", "author": None, "name": "Test",
                      "subgroup": None, "image_type": "battlemap",
                      "relative_path": "map.png", "import_job_id": "job",
                      "content_hash": None,
                  },
                  pipeline_config=webp_cfg,
              )

          assert result["status"] == "success"
          assert result["image_data"]["storage_key"].endswith(".webp")
          if result["image_data"]["thumbnail_key"]:
              assert result["image_data"]["thumbnail_key"].endswith(".webp")

      def test_precomputed_hash_discarded_on_conversion(self, tmp_path, webp_cfg):
          from backend.pipeline.prepare import prepare_single_image
          from backend.app.services.image_store import ImageStore

          src = tmp_path / "map.jpg"
          PILImage.new("RGB", (100, 80)).save(str(src), format="JPEG")

          with open(src, "rb") as f:
              original_hash = hashlib.sha256(f.read()).hexdigest()

          image_store = ImageStore(tmp_path / "store")
          thumb_store = ImageStore(tmp_path / "thumbs")

          with patch("backend.pipeline.prepare.get_image_store", return_value=image_store), \
               patch("backend.pipeline.tasks.image_processing.get_thumbnail_store", return_value=thumb_store), \
               patch("backend.pipeline.prepare.pipeline_db"):
              result = prepare_single_image(
                  str(src),
                  metadata={
                      "group_name": "Test", "author": None, "name": "Test",
                      "subgroup": None, "image_type": "battlemap",
                      "relative_path": "map.jpg", "import_job_id": "job",
                      "content_hash": original_hash,  # Pre-computed from original
                  },
                  pipeline_config=webp_cfg,
              )

          stored_hash = result["image_data"]["content_hash"]
          assert stored_hash != original_hash, "Hash must be recomputed from WebP, not original"

      def test_colors_extracted_after_webp_conversion(self, tmp_path, webp_cfg):
          """Regression: _extract_colors must use image_path_obj (converted), not image_path (deleted)."""
          from backend.pipeline.prepare import prepare_single_image
          from backend.app.services.image_store import ImageStore

          src = tmp_path / "map.png"
          PILImage.new("RGB", (100, 80), color=(200, 100, 50)).save(str(src))

          image_store = ImageStore(tmp_path / "store")
          thumb_store = ImageStore(tmp_path / "thumbs")

          with patch("backend.pipeline.prepare.get_image_store", return_value=image_store), \
               patch("backend.pipeline.tasks.image_processing.get_thumbnail_store", return_value=thumb_store), \
               patch("backend.pipeline.prepare.pipeline_db"):
              result = prepare_single_image(
                  str(src),
                  metadata={
                      "group_name": "Test", "author": None, "name": "Test",
                      "subgroup": None, "image_type": "battlemap",
                      "relative_path": "map.png", "import_job_id": "job",
                      "content_hash": None,
                  },
                  pipeline_config=webp_cfg,
              )

          assert result["status"] == "success"
          assert isinstance(result["image_data"]["colors"], list)
  ```

- [ ] **Step 2: Run to confirm failure**

  ```bash
  uv run pytest backend/tests/unit/test_webp_conversion.py::TestPrepareWithWebP -v
  ```
  Expected: the tests run but assertions fail (storage key still `.png`).

- [ ] **Step 3: Read `prepare.py` lines 230–245 carefully before editing**

  The insertion order matters:
  - Line 233: `storage_key_stem = uuid.uuid4().hex[:12]`
  - Line 234: `ext = image_path_obj.suffix.lower()`
  - Line 235: `storage_key = f"{storage_key_stem}{ext}"`
  - **Line 236: `image_store.put(storage_key, image_path_obj)`** ← WebP conversion must happen BEFORE this
  - Line 240: `content_hash = _compute_file_hash(image_path_obj)` ← must hash the post-conversion file

  Insert the conversion block **between line 235 and line 236**:

  ```python
  # --- Optional WebP conversion (before copying to store) ---
  # Must happen before image_store.put() so the stored file is WebP.
  # Must happen before _compute_file_hash() so the hash matches stored content.
  _use_webp = pipeline_config.use_webp if pipeline_config is not None else False
  if _use_webp:
      from backend.pipeline.tasks.webp_conversion import convert_to_webp as _convert_webp
      _converted = _convert_webp(image_path_obj)
      if _converted != image_path_obj:
          # Conversion happened — update all path/key/hash references
          image_path_obj = _converted
          ext = ".webp"
          storage_key = f"{storage_key_stem}{ext}"
          content_hash = None  # Discard pre-computed hash; _compute_file_hash runs below
  ```

  Then update the `_gen_thumbs` call for normal images (around line 271):

  ```python
  thumbnail_result = _gen_thumbs(str(image_path_obj), storage_key_stem, use_webp=_use_webp)
  ```

  For the **video branch** (around line 264), keep the call without WebP:

  ```python
  thumbnail_result = _gen_thumbs(str(frame_path), storage_key_stem, use_webp=False)
  ```

  Video thumbnails are always JPEG (the frame is a temporary JPEG extract; the stored file is the original video, not converted).

  Also update **both `_detect_grid` call sites** (around lines 311 and 314) and the **`_extract_colors` call** (around line 274) — all three must open the converted file, not the deleted original:

  ```python
  # Line 274 — replace image_path with str(image_path_obj):
  colors = _extract_colors(str(image_path_obj), pipeline_config=pipeline_config)

  # Line 311 — replace image_path with str(image_path_obj):
  grid_result = _detect_grid(
      str(image_path_obj), width, height, size_only=False, pipeline_config=_cfg
  )
  # Line 314 — similarly:
  grid_result = _detect_grid(
      str(image_path_obj), width, height, size_only=True, pipeline_config=_cfg
  )
  ```

  After WebP conversion, `image_path` (the original function argument) still points to the deleted staged file. Only `image_path_obj` is updated to the new `.webp` path.

- [ ] **Step 4: Run integration tests**

  ```bash
  uv run pytest backend/tests/unit/test_webp_conversion.py -v
  uv run pytest backend/tests/ -x -q
  ```
  Expected: all PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/pipeline/prepare.py backend/tests/unit/test_webp_conversion.py
  git commit -m "feat(pipeline): wire WebP conversion into prepare_single_image"
  ```

---

## Chunk 3: Electron Config, Setup Wizard & Frontend UI

Files:
- Modify: `electron/src/config.ts`
- Modify: `electron/src/sidecar.ts`
- Modify: `electron/src/main.ts`
- Modify: `electron/src/preload.ts`
- Modify: `electron/src/setup.preload.ts`
- Modify: `electron/setup.html`
- Modify: `frontend/src/electron.d.ts`
- Modify: `frontend/src/components/settings/SettingsTabContent.tsx`
- Modify: `frontend/src/components/LibraryInfoDialog.tsx`
- Modify: `design/storage.md`
- Modify: `design/electron.md`

---

### Task 3.1: Electron config — new schema + migration

**Files:**
- Modify: `electron/src/config.ts`

- [ ] **Step 1: Read the current `config.ts`**

  Read `electron/src/config.ts` in full.

- [ ] **Step 2: Rewrite `config.ts`**

  ```typescript
  import { app } from 'electron'
  import * as fs from 'fs'
  import * as path from 'path'

  interface AppConfig {
    appDataDir: string
    imageLibraryDir: string
    convertToWebp: boolean
  }

  /** Legacy config shape written by older versions. */
  interface LegacyConfig {
    dataDir?: string
  }

  function getConfigPath(): string {
    return path.join(app.getPath('userData'), 'scene-atlas-config.json')
  }

  /** Migrate a legacy single-root config to the two-root schema.
   *
   * appDataDir      ← dataDir           (unchanged; fast data already lives here)
   * imageLibraryDir ← dataDir/store/images  (existing image root becomes new library root)
   */
  function migrateLegacyConfig(legacy: LegacyConfig): AppConfig {
    const dataDir = legacy.dataDir!
    return {
      appDataDir: dataDir,
      imageLibraryDir: path.join(dataDir, 'store', 'images'),
      convertToWebp: true,
    }
  }

  export function loadConfig(): AppConfig | null {
    const configPath = getConfigPath()
    if (!fs.existsSync(configPath)) return null
    try {
      const raw = fs.readFileSync(configPath, 'utf-8')
      const parsed = JSON.parse(raw) as AppConfig & LegacyConfig

      // Migration: old config has dataDir but not appDataDir
      if (parsed.dataDir && !parsed.appDataDir) {
        const migrated = migrateLegacyConfig(parsed)
        saveConfig(migrated)  // Persist migrated config (removes dataDir key)
        return migrated
      }

      if (!parsed.appDataDir || !parsed.imageLibraryDir) return null
      return {
        appDataDir: parsed.appDataDir,
        imageLibraryDir: parsed.imageLibraryDir,
        convertToWebp: parsed.convertToWebp ?? true,
      }
    } catch {
      return null
    }
  }

  export function saveConfig(config: AppConfig): void {
    const configPath = getConfigPath()
    fs.mkdirSync(path.dirname(configPath), { recursive: true })
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2))
  }

  export function getDefaultDirs(): { appDataDir: string; imageLibraryDir: string } {
    const base = path.join(app.getPath('documents'), 'Scene Atlas')
    return {
      appDataDir: path.join(base, 'data'),
      imageLibraryDir: path.join(base, 'images'),
    }
  }
  ```

- [ ] **Step 3: Compile check**

  ```bash
  cd /home/joe/code/scene-atlas/electron && npx tsc --noEmit
  ```
  Expected: TypeScript errors at `main.ts` call sites (old `getDefaultDataDir`, `loadConfig` shape) — these will be fixed in Task 3.3.

- [ ] **Step 4: Commit**

  ```bash
  git add electron/src/config.ts
  git commit -m "feat(electron): two-root config schema with legacy migration"
  ```

---

### Task 3.2: Update sidecar spawn

**Files:**
- Modify: `electron/src/sidecar.ts`

- [ ] **Step 1: Read the current `sidecar.ts`** in full.

- [ ] **Step 2: Update `spawnSidecar` signature and spawn call**

  ```typescript
  export function spawnSidecar(
    port: number,
    appDataDir: string,
    imageLibraryDir: string,
    convertToWebp: boolean,
    onReady: (port: number) => void,
    onLog: (line: string) => void,
  ): ChildProcess {
    const sidecarPath = getSidecarPath()
    const child = spawn(
      sidecarPath,
      ['--port', String(port), '--app-data-dir', appDataDir, '--image-library-dir', imageLibraryDir],
      {
        stdio: ['ignore', 'pipe', 'pipe'],
        env: {
          ...process.env,
          CONVERT_TO_WEBP: convertToWebp ? '1' : '0',
        },
      },
    )
    // ... rest of the function (stdout/stderr handlers, error/exit handlers) unchanged
  ```

- [ ] **Step 3: Compile check** (errors in main.ts call site are expected)

  ```bash
  cd /home/joe/code/scene-atlas/electron && npx tsc --noEmit 2>&1 | grep -v "main.ts"
  ```
  Expected: no errors outside of main.ts.

- [ ] **Step 4: Commit**

  ```bash
  git add electron/src/sidecar.ts
  git commit -m "feat(electron): update sidecar to pass --app-data-dir / --image-library-dir"
  ```

---

### Task 3.3: Update main process IPC handlers

**Files:**
- Modify: `electron/src/main.ts`

- [ ] **Step 1: Read `main.ts` in full** (it is ~250 lines; read all of it).

- [ ] **Step 2: Update module-level state variables**

  Remove `let currentDataDir: string | null = null`.
  Add:

  ```typescript
  let currentAppDataDir: string | null = null
  let currentImageLibraryDir: string | null = null
  let currentConvertToWebp: boolean = true
  ```

- [ ] **Step 3: Replace all IPC handlers**

  Remove handlers: `setup:get-default-dir`, `setup:complete`, `system:get-data-dir`, `system:open-data-dir`, `system:choose-data-dir`, `system:change-data-dir`.

  Add new handlers:

  ```typescript
  // ── Setup window IPC ────────────────────────────────────────────────────────

  ipcMain.handle('setup:get-default-dirs', () => getDefaultDirs())

  ipcMain.handle('setup:choose-directory', async () => {
    const result = await dialog.showOpenDialog(setupWindow!, {
      title: 'Choose Folder',
      properties: ['openDirectory', 'createDirectory'],
      buttonLabel: 'Select Folder',
    })
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.on('setup:complete', (_event, appDataDir: string, imageLibraryDir: string, convertToWebp: boolean) => {
    // Create both roots before launching the backend (backend validates they exist)
    fs.mkdirSync(appDataDir, { recursive: true })
    fs.mkdirSync(imageLibraryDir, { recursive: true })
    saveConfig({ appDataDir, imageLibraryDir, convertToWebp })
    setupWindow?.close()
    setupWindow = null
    launchApp(appDataDir, imageLibraryDir, convertToWebp)
  })

  // ── System settings IPC ─────────────────────────────────────────────────────

  ipcMain.handle('system:get-app-data-dir', () => currentAppDataDir)
  ipcMain.handle('system:get-image-library-dir', () => currentImageLibraryDir)

  ipcMain.handle('system:choose-app-data-dir', async () => {
    const result = await dialog.showOpenDialog(mainWindow!, {
      title: 'Choose App Data Location',
      defaultPath: currentAppDataDir ?? getDefaultDirs().appDataDir,
      properties: ['openDirectory', 'createDirectory'],
      buttonLabel: 'Select Folder',
    })
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('system:choose-image-library-dir', async () => {
    const result = await dialog.showOpenDialog(mainWindow!, {
      title: 'Choose Image Library Location',
      defaultPath: currentImageLibraryDir ?? getDefaultDirs().imageLibraryDir,
      properties: ['openDirectory', 'createDirectory'],
      buttonLabel: 'Select Folder',
    })
    return result.canceled ? null : result.filePaths[0]
  })

  // Saves new paths to config and restarts.
  // Called only when user explicitly clicks "Restart Now" in the Settings UI.
  ipcMain.handle(
    'system:change-storage-dirs',
    (_event, newAppDataDir: string, newImageLibraryDir: string) => {
      saveConfig({
        appDataDir: newAppDataDir,
        imageLibraryDir: newImageLibraryDir,
        convertToWebp: currentConvertToWebp,
      })
      app.relaunch()
      app.exit(0)
    },
  )
  ```

- [ ] **Step 4: Update `launchApp` function signature and parameter wiring**

  Update the function signature and the three lines that store current state. Keep all existing logging, crash-reporting, and sidecar error-handling code intact — only update the parts shown below:

  ```typescript
  // Change signature from: launchApp(dataDir: string)
  // Change to:
  async function launchApp(appDataDir: string, imageLibraryDir: string, convertToWebp: boolean): Promise<void> {
    // Replace: currentDataDir = dataDir
    // With:
    currentAppDataDir = appDataDir
    currentImageLibraryDir = imageLibraryDir
    currentConvertToWebp = convertToWebp

    // ... keep createMainWindow(), isDev branch, findFreePort() unchanged ...

    // Update the spawnSidecar call to pass new args:
    spawnSidecar(port, appDataDir, imageLibraryDir, convertToWebp,
      (p) => mainWindow?.webContents.send('backend-ready', p),
      (line) => { /* keep existing log-line handler */ },
    )
    // ... keep all remaining sidecar exit/error handlers unchanged ...
  }
  ```

- [ ] **Step 5: Update `app.whenReady()` call site and `app.on('activate', ...)` handler**

  Find the block at the bottom of `main.ts` where `loadConfig()` is called and update it:

  ```typescript
  const config = loadConfig()
  if (config) {
    launchApp(config.appDataDir, config.imageLibraryDir, config.convertToWebp)
  } else {
    showSetupWindow()
  }
  ```

  Also find the `app.on('activate', ...)` handler (macOS dock re-open) and update its `launchApp` call to the new three-argument signature:

  ```typescript
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      const config = loadConfig()
      if (config) {
        launchApp(config.appDataDir, config.imageLibraryDir, config.convertToWebp)
      } else {
        showSetupWindow()
      }
    }
  })
  ```

- [ ] **Step 6: Compile check**

  ```bash
  cd /home/joe/code/scene-atlas/electron && npx tsc --noEmit
  ```
  Expected: no errors.

- [ ] **Step 7: Commit**

  ```bash
  git add electron/src/main.ts
  git commit -m "feat(electron): update main IPC for two-root storage"
  ```

---

### Task 3.4: Update preload scripts

**Files:**
- Modify: `electron/src/preload.ts`
- Modify: `electron/src/setup.preload.ts`

- [ ] **Step 1: Update `preload.ts`**

  Replace the `electronAPI` object — remove old data-dir methods, add new:

  ```typescript
  import { contextBridge, ipcRenderer } from 'electron'

  contextBridge.exposeInMainWorld('electronAPI', {
    platform: process.platform,

    onBackendReady: (callback: (port: number) => void) => {
      ipcRenderer.once('backend-ready', (_event, port: number) => callback(port))
    },
    onBackendError: (callback: (message: string) => void) => {
      ipcRenderer.once('backend-error', (_event, message: string) => callback(message))
    },

    // Storage path IPC
    getAppDataDir: (): Promise<string | null> => ipcRenderer.invoke('system:get-app-data-dir'),
    getImageLibraryDir: (): Promise<string | null> => ipcRenderer.invoke('system:get-image-library-dir'),
    chooseAppDataDir: (): Promise<string | null> => ipcRenderer.invoke('system:choose-app-data-dir'),
    chooseImageLibraryDir: (): Promise<string | null> => ipcRenderer.invoke('system:choose-image-library-dir'),
    // Saves config AND restarts. Call only when user confirms they've moved files.
    changeStorageDirs: (appDataDir: string, imageLibraryDir: string): Promise<void> =>
      ipcRenderer.invoke('system:change-storage-dirs', appDataDir, imageLibraryDir),

    // Filesystem access for drag-and-drop folder traversal
    readDirectory: (dirPath: string): Promise<Array<{ relativePath: string; absolutePath: string }>> =>
      ipcRenderer.invoke('fs:read-directory', dirPath),
    readFileBytes: (absolutePath: string): Promise<{ data: Uint8Array }> =>
      ipcRenderer.invoke('fs:read-file-bytes', absolutePath),
  })
  ```

- [ ] **Step 2: Update `setup.preload.ts`**

  ```typescript
  import { contextBridge, ipcRenderer } from 'electron'

  contextBridge.exposeInMainWorld('setupAPI', {
    getDefaultDirs: (): Promise<{ appDataDir: string; imageLibraryDir: string }> =>
      ipcRenderer.invoke('setup:get-default-dirs'),

    chooseDirectory: (): Promise<string | null> =>
      ipcRenderer.invoke('setup:choose-directory'),

    complete: (appDataDir: string, imageLibraryDir: string, convertToWebp: boolean): void =>
      ipcRenderer.send('setup:complete', appDataDir, imageLibraryDir, convertToWebp),
  })
  ```

- [ ] **Step 3: Compile check**

  ```bash
  cd /home/joe/code/scene-atlas/electron && npx tsc --noEmit
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add electron/src/preload.ts electron/src/setup.preload.ts
  git commit -m "feat(electron): update preload IPC surface for two-root storage"
  ```

---

### Task 3.5: Replace setup.html

**Files:**
- Modify: `electron/setup.html`

- [ ] **Step 1: Read the current `electron/setup.html`** to note the window drag region and meta tags.

- [ ] **Step 2: Read the approved v5 mockup**

  Read `.superpowers/brainstorm/361892-1773536017/setup-wizard-v5.html` in full.

- [ ] **Step 3: Copy the v5 content into `electron/setup.html`**

  Before copying, **add the following `id` attributes** to the relevant elements in the v5 HTML so that the integration script (Step 4) can wire them up by ID:

  - First `.dir-display` element (app data path): add `id="app-data-dir"`
  - Second `.dir-display` element (image library path): add `id="image-library-dir"`
  - First `.browse-btn` element (app data browse): add `id="browse-app-data"`
  - Second `.browse-btn` element (image library browse): add `id="browse-image-library"`

  Keep the window drag region (`-webkit-app-region: drag`) from the current `setup.html` if it exists.

- [ ] **Step 4: Add the integration script**

  Replace or supplement the existing `<script>` block at the bottom of `setup.html` with:

  ```html
  <script>
    let appDataDir = ''
    let imageLibraryDir = ''
    let convertToWebp = true  // default on

    // Populate default dirs on load
    window.setupAPI.getDefaultDirs().then(function(dirs) {
      appDataDir = dirs.appDataDir
      imageLibraryDir = dirs.imageLibraryDir
      document.getElementById('app-data-dir').textContent = appDataDir
      document.getElementById('image-library-dir').textContent = imageLibraryDir
    })

    document.getElementById('browse-app-data').addEventListener('click', async function() {
      const chosen = await window.setupAPI.chooseDirectory()
      if (chosen) {
        appDataDir = chosen
        document.getElementById('app-data-dir').textContent = chosen
      }
    })

    document.getElementById('browse-image-library').addEventListener('click', async function() {
      const chosen = await window.setupAPI.chooseDirectory()
      if (chosen) {
        imageLibraryDir = chosen
        document.getElementById('image-library-dir').textContent = chosen
      }
    })

    // WebP toggle
    const toggleBtn = document.querySelector('.toggle-switch')
    const toggleState = document.querySelector('.toggle-state')

    toggleBtn.addEventListener('click', function() {
      convertToWebp = !convertToWebp
      toggleBtn.classList.toggle('off', !convertToWebp)
      toggleState.textContent = convertToWebp ? 'On' : 'Off'
      toggleState.style.color = convertToWebp ? 'var(--primary)' : 'var(--fg-muted)'
    })

    // Get Started
    document.querySelector('.start-btn').addEventListener('click', function() {
      if (!appDataDir || !imageLibraryDir) return
      window.setupAPI.complete(appDataDir, imageLibraryDir, convertToWebp)
    })
  </script>
  ```

- [ ] **Step 5: Manual smoke test** (Electron dev mode)

  Temporarily delete or rename `~/.config/Scene Atlas/scene-atlas-config.json` (or the platform equivalent) to force the setup window to appear:

  ```bash
  # On Linux:
  mv ~/.config/Scene\ Atlas/scene-atlas-config.json ~/.config/Scene\ Atlas/scene-atlas-config.json.bak
  ```

  Then launch the app in dev mode and verify:
  - Both directory pickers show default paths
  - Browse buttons open a folder dialog
  - WebP toggle animates correctly
  - "Get Started" button sends data and launches the main window
  - Restore the config file afterwards.

- [ ] **Step 6: Commit**

  ```bash
  git add electron/setup.html
  git commit -m "feat(ui): replace setup wizard with two-root + WebP toggle design"
  ```

---

### Task 3.6: Update frontend type declarations

**Files:**
- Modify: `frontend/src/electron.d.ts`

- [ ] **Step 1: Replace `ElectronAPI` interface**

  ```typescript
  interface ElectronAPI {
    readonly platform: 'darwin' | 'win32' | 'linux'

    onBackendReady(callback: (port: number) => void): void
    onBackendError(callback: (message: string) => void): void

    // Storage path IPC
    getAppDataDir(): Promise<string | null>
    getImageLibraryDir(): Promise<string | null>
    chooseAppDataDir(): Promise<string | null>
    chooseImageLibraryDir(): Promise<string | null>
    /** Saves config and restarts the app. Call only when user confirms file-move intent. */
    changeStorageDirs(appDataDir: string, imageLibraryDir: string): Promise<void>

    // Filesystem access for drag-and-drop folder traversal
    readDirectory(dirPath: string): Promise<Array<{ relativePath: string; absolutePath: string }>>
    readFileBytes(absolutePath: string): Promise<{ data: Uint8Array }>
  }

  declare global {
    interface Window {
      electronAPI?: ElectronAPI
      __SCENE_ATLAS_PORT__?: number
    }
  }

  export {}
  ```

- [ ] **Step 2: Run frontend type check — expect errors at old call sites**

  ```bash
  cd /home/joe/code/scene-atlas/frontend && npx tsc --noEmit
  ```
  Expected: errors in `LibraryInfoDialog.tsx` for `getDataDir`, `openDataDir`, `chooseDataDir`, `changeDataDir`. These are fixed in Task 3.7.

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/electron.d.ts
  git commit -m "feat(frontend): update ElectronAPI types for two-root storage"
  ```

---

### Task 3.7: Update `LibraryInfoDialog` and `SettingsTabContent`

**Files:**
- Modify: `frontend/src/components/LibraryInfoDialog.tsx`
- Modify: `frontend/src/components/settings/SettingsTabContent.tsx`

- [ ] **Step 1: Read both files in full** before making any changes.

- [ ] **Step 2: Update `LibraryInfoDialog.tsx`**

  The library tab currently shows a single data directory with browse/confirm/relaunch flow. Replace with a read-only display of both directories.

  **State changes:**
  - Remove: `locationPhase`, `pendingDir`, `dataDir`
  - Add: `appDataDir: string | null`, `imageLibraryDir: string | null`

  **Handler changes:**
  - Remove: `handleChooseDir`, `handleConfirmChange`, `handleCancelChange`, `handleOpenInExplorer`
  - The "Open in Explorer" buttons are removed entirely. The library tab shows paths as read-only info; Settings is the place to manage them.

  **useEffect update:**
  ```tsx
  useEffect(() => {
    if (open && window.electronAPI) {
      window.electronAPI.getAppDataDir().then(setAppDataDir)
      window.electronAPI.getImageLibraryDir().then(setImageLibraryDir)
    }
  }, [open])
  ```

  **Library tab UI update** — replace the old directory section with:
  ```tsx
  {isElectron && (
    <div className="space-y-1">
      <p className="section-label">Storage</p>
      <div className="space-y-0.5">
        <p className="text-xs text-muted-foreground">App data: <span className="font-mono">{appDataDir ?? '—'}</span></p>
        <p className="text-xs text-muted-foreground">Images: <span className="font-mono">{imageLibraryDir ?? '—'}</span></p>
      </div>
      <p className="text-xs text-muted-foreground/60">To change, go to Settings → Storage Locations.</p>
    </div>
  )}
  ```

- [ ] **Step 3: Add `convert_to_webp` to the frontend `AppSettings` type**

  Open `frontend/src/types/index.ts` and find the `AppSettings` interface. Add the new field (place it with other import-related settings):

  ```typescript
  convert_to_webp: boolean
  ```

  Run the frontend type check to confirm no immediate errors from this addition:

  ```bash
  cd /home/joe/code/scene-atlas/frontend && npx tsc --noEmit 2>&1 | head -20
  ```

- [ ] **Step 4: Update `SettingsTabContent.tsx` — add Storage Locations + WebP toggle**

  **Add state** (within the component, after existing `useImperativeHandle`):

  ```tsx
  const isElectron = typeof window !== 'undefined' && !!window.electronAPI
  const [appDataDir, setAppDataDir] = useState<string | null>(null)
  const [imageLibraryDir, setImageLibraryDir] = useState<string | null>(null)
  const [pendingAppDataDir, setPendingAppDataDir] = useState<string | null>(null)
  const [pendingImageLibraryDir, setPendingImageLibraryDir] = useState<string | null>(null)

  useEffect(() => {
    if (dialogOpen && isElectron) {
      window.electronAPI!.getAppDataDir().then(setAppDataDir)
      window.electronAPI!.getImageLibraryDir().then(setImageLibraryDir)
    }
  }, [dialogOpen, isElectron])

  const handleChooseAppDataDir = async () => {
    const chosen = await window.electronAPI?.chooseAppDataDir()
    if (chosen && chosen !== appDataDir) setPendingAppDataDir(chosen)
  }

  const handleChooseImageLibraryDir = async () => {
    const chosen = await window.electronAPI?.chooseImageLibraryDir()
    if (chosen && chosen !== imageLibraryDir) setPendingImageLibraryDir(chosen)
  }

  const handleApplyStorageChange = () => {
    if (!appDataDir || !imageLibraryDir) return  // IPC hasn't loaded yet; wait
    window.electronAPI?.changeStorageDirs(
      pendingAppDataDir ?? appDataDir,
      pendingImageLibraryDir ?? imageLibraryDir,
    )
    // changeStorageDirs saves config and calls app.relaunch() — no return
  }
  ```

  **Add Storage Locations section** as the **first section** in the return JSX (before the current General section):

  ```tsx
  {isElectron && (
    <section className="space-y-3">
      <p className="section-label mb-3">Storage Locations</p>

      <StoragePathRow
        label="App data location"
        description="Database, thumbnails & search index. SSD recommended."
        current={appDataDir}
        pending={pendingAppDataDir}
        onBrowse={handleChooseAppDataDir}
        requiresRestart
      />

      <StoragePathRow
        label="Image library location"
        description="Original images and backups. Any drive including external storage."
        current={imageLibraryDir}
        pending={pendingImageLibraryDir}
        onBrowse={handleChooseImageLibraryDir}
        requiresRestart
      />

      {(pendingAppDataDir || pendingImageLibraryDir) && (
        <div className="space-y-2 rounded border border-amber-500/20 bg-amber-500/5 p-3">
          <p className="text-xs text-muted-foreground">
            Changing a path does not move your files. Move them manually before restarting.
          </p>
          <button
            type="button"
            onClick={handleApplyStorageChange}
            className="text-xs font-medium text-primary hover:underline"
          >
            Restart Now to Apply
          </button>
        </div>
      )}

      <div className="border-t border-border/30" />
    </section>
  )}
  ```

  **Define `StoragePathRow`** as a local component above `SettingsTabContent`:

  ```tsx
  interface StoragePathRowProps {
    label: string
    description: string
    current: string | null
    pending: string | null
    onBrowse: () => void
    requiresRestart?: boolean
  }

  function StoragePathRow({ label, description, current, pending, onBrowse, requiresRestart }: StoragePathRowProps) {
    const display = pending ?? current ?? '—'
    const changed = pending != null
    return (
      <SettingRow label={label} description={description} requiresRestart={requiresRestart}>
        <div className="flex items-center gap-2">
          <span
            className={`max-w-[180px] truncate text-xs font-mono ${changed ? 'text-primary' : 'text-muted-foreground'}`}
            title={display}
          >
            {display}
          </span>
          <button
            type="button"
            onClick={onBrowse}
            className="shrink-0 rounded border border-border/50 px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
          >
            Browse
          </button>
        </div>
      </SettingRow>
    )
  }
  ```

  **Add WebP toggle** inside the Import Limits section (before the closing `<div className="border-t ..."/>`):

  ```tsx
  <SettingRow
    label="Convert imports to WebP"
    description="Reduces file size 20–40% with no quality loss. Applies to new imports only."
  >
    <button
      type="button"
      onClick={() => setField('convert_to_webp', !val('convert_to_webp'))}
      aria-label="Toggle WebP conversion"
      aria-pressed={val('convert_to_webp') as boolean}
      className={`h-6 w-11 rounded-full transition-colors flex items-center px-1 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40 ${
        val('convert_to_webp') ? 'bg-primary' : 'bg-secondary border border-border/50'
      }`}
    >
      <div
        className={`h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
          val('convert_to_webp') ? 'translate-x-5' : 'translate-x-0'
        }`}
      />
    </button>
  </SettingRow>
  ```

  Add `useState` and `useEffect` to the React imports (neither is currently imported in `SettingsTabContent.tsx`).

- [ ] **Step 5: Run frontend type check**

  ```bash
  cd /home/joe/code/scene-atlas/frontend && npx tsc --noEmit
  ```
  Expected: no errors.

- [ ] **Step 6: Run ESLint with auto-fix**

  ```bash
  cd /home/joe/code/scene-atlas/frontend && npx eslint src --ext .ts,.tsx --fix
  ```

- [ ] **Step 7: Run Python linter**

  ```bash
  cd /home/joe/code/scene-atlas && uv run ruff format backend && uv run ruff check backend --fix
  ```

- [ ] **Step 8: Run full test suite**

  ```bash
  uv run pytest backend/tests/ -x -q
  ```
  Expected: all PASS.

- [ ] **Step 9: Commit**

  ```bash
  git add frontend/src/types/index.ts \
          frontend/src/components/LibraryInfoDialog.tsx \
          frontend/src/components/settings/SettingsTabContent.tsx
  git commit -m "feat(ui): add storage locations + WebP toggle to settings, update library dialog"
  ```

---

### Task 3.8: Update design docs

**Files:**
- Modify: `design/storage.md`
- Modify: `design/electron.md`

- [ ] **Step 1: Read `design/storage.md`** in full.

- [ ] **Step 2: Update `design/storage.md`**

  - Change the "Filesystem — ImageStore" section to reflect the new flat root: `{IMAGE_LIBRARY_DIR}/a1/b2/...` instead of `data/store/images/a1/b2/...`
  - Update thumbnails path to `{APP_DATA_DIR}/store/thumbnails/`
  - Update staging path to `{APP_DATA_DIR}/staging/`
  - Update backups section to `{IMAGE_LIBRARY_DIR}/backups/` (note the migration quirk for existing installs)
  - Update the "SQLite Database" location to `{APP_DATA_DIR}/battlemap.db`
  - Update the "Qdrant Vector Store" location to `{APP_DATA_DIR}/qdrant_local`

- [ ] **Step 3: Read `design/electron.md`** in full.

- [ ] **Step 4: Update `design/electron.md`**

  - Update the Config Storage table: remove `dataDir`, add `appDataDir`, `imageLibraryDir`, `convertToWebp`
  - Update the IPC Channels tables for both setup and main windows
  - Update the `window.electronAPI` surface listing
  - Update the startup sequence diagram to show the new `launchApp(appDataDir, imageLibraryDir, convertToWebp)` signature
  - Update the sidecar spawn args

- [ ] **Step 5: Commit**

  ```bash
  git add design/storage.md design/electron.md
  git commit -m "docs: update storage and electron design docs for two-root config"
  ```

---

## Final Verification

- [ ] Run full test suite: `uv run pytest backend/tests/ -v`
- [ ] Run frontend type check: `cd frontend && npx tsc --noEmit`
- [ ] Run ESLint: `cd frontend && npx eslint src --ext .ts,.tsx`
- [ ] Run Ruff: `uv run ruff format backend && uv run ruff check backend`
- [ ] Manual smoke test — new install: delete config, launch app, verify setup wizard shows both pickers and WebP toggle, complete setup, verify main app loads.
- [ ] Manual smoke test — migration: create a `scene-atlas-config.json` with the old `{ "dataDir": "/some/path" }` schema, launch app, verify it migrates silently and the main app loads.
- [ ] Manual smoke test — import: upload an image with WebP conversion enabled, verify the stored file is `.webp` and the thumbnail is `.webp`.
