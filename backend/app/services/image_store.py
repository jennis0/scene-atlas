"""Object-store style image storage with hash-sharded filesystem.

Stores images using UUID-based keys in a sharded directory structure:
    base_dir/ab/cd/abcdef1234567890.jpg

This keeps any single directory small (max ~256 entries per level),
scales to O(100k+) images, and the interface is designed to be
swappable to S3/MinIO later.
"""

import os
import shutil
from pathlib import Path


class ImageStore:
    """Hash-sharded filesystem storage for images."""

    def __init__(self, base_dir: Path):
        # The root isn't created here: a missing library folder must stay missing (an
        # unmounted drive), and the startup check decides when a new one is made.
        self.base_dir = base_dir

    def _key_to_path(self, key: str) -> Path:
        """Convert storage key to sharded path.

        Example: "a1b2c3d4e5f6.jpg" -> base_dir/a1/b2/a1b2c3d4e5f6.jpg
        """
        stem = Path(key).stem
        return self.base_dir / stem[:2] / stem[2:4] / key

    def put(self, key: str, source_path: Path) -> Path:
        """Copy *source_path* into the store under *key*; returns the stored path."""
        dest = self._key_to_path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest)
        return dest

    def put_bytes(self, key: str, data: bytes) -> Path:
        """Write *data* into the store under *key*; returns the stored path."""
        dest = self._key_to_path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    def get_path(self, key: str) -> Path:
        """Resolve a storage key to its filesystem path."""
        return self._key_to_path(key)

    def stat(self, key: str) -> os.stat_result | None:
        """The stored file's size and modification time, or None if it isn't there."""
        try:
            return self._key_to_path(key).stat()
        except OSError:
            return None

    def local_path(self, key: str) -> Path:
        """The stored file to read (the source interface, ``services.originals``). Raises
        ``FileNotFoundError`` if it isn't there."""
        path = self._key_to_path(key)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def exists(self, key: str) -> bool:
        """Check if a key exists in the store."""
        return self._key_to_path(key).exists()

    def delete(self, key: str) -> bool:
        """Delete *key* from the store; False if it didn't exist."""
        path = self._key_to_path(key)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
