"""Object-store style image storage with hash-sharded filesystem.

Stores images using UUID-based keys in a sharded directory structure:
    base_dir/ab/cd/abcdef1234567890.jpg

This keeps any single directory small (max ~256 entries per level),
scales to O(100k+) images, and the interface is designed to be
swappable to S3/MinIO later.
"""

import shutil
import uuid
from pathlib import Path


class ImageStore:
    """Hash-sharded filesystem storage for images."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _key_to_path(self, key: str) -> Path:
        """Convert storage key to sharded path.

        Example: "a1b2c3d4e5f6.jpg" -> base_dir/a1/b2/a1b2c3d4e5f6.jpg
        """
        stem = Path(key).stem
        return self.base_dir / stem[:2] / stem[2:4] / key

    def put(self, key: str, source_path: Path) -> Path:
        """Copy a file into the store.

        Args:
            key: Storage key (e.g., "a1b2c3d4.jpg")
            source_path: Path to the source file

        Returns:
            The full filesystem path where the file was stored
        """
        dest = self._key_to_path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest)
        return dest

    def put_bytes(self, key: str, data: bytes) -> Path:
        """Write raw bytes into the store.

        Args:
            key: Storage key
            data: File contents as bytes

        Returns:
            The full filesystem path where the file was stored
        """
        dest = self._key_to_path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    def get_path(self, key: str) -> Path:
        """Resolve a storage key to its filesystem path."""
        return self._key_to_path(key)

    def exists(self, key: str) -> bool:
        """Check if a key exists in the store."""
        return self._key_to_path(key).exists()

    def delete(self, key: str) -> bool:
        """Delete a file from the store.

        Returns:
            True if the file was deleted, False if it didn't exist
        """
        path = self._key_to_path(key)
        if path.exists():
            path.unlink()
            return True
        return False

    @staticmethod
    def generate_key(original_filename: str) -> str:
        """Generate a unique storage key preserving the file extension.

        Args:
            original_filename: Original filename (used only for extension)

        Returns:
            UUID-based key like "a1b2c3d4e5f67890abcdef1234567890.jpg"
        """
        ext = Path(original_filename).suffix.lower()
        return f"{uuid.uuid4().hex}{ext}"
