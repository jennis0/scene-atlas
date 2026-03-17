"""LanceDB vector database service (embedded disk-backed mode).

Uses lancedb.connect(path=...) for memory-mapped disk storage — no separate
server process needed.  A threading.RLock serialises write operations (upsert,
delete, table management).  Read operations (search, retrieve) snapshot the
table reference and are safe to call concurrently with writes, but will raise
RuntimeError if called after close().
"""

import logging
import shutil
import threading
from pathlib import Path

import lancedb
import numpy as np
import pyarrow as pa

from ..config import settings

logger = logging.getLogger(__name__)


def _table_schema(vector_size: int) -> pa.Schema:
    """Return the PyArrow schema for an embeddings table."""
    return pa.schema(
        [
            pa.field("id", pa.int64()),
            pa.field("vector", pa.list_(pa.float32(), vector_size)),
            pa.field("image_id", pa.int64()),
            pa.field("filename", pa.utf8()),
            pa.field("author", pa.utf8()),
            pa.field("base_name", pa.utf8()),
        ]
    )


class LanceDBService:
    """Thread-safe LanceDB service backed by disk-based (memory-mapped) storage."""

    def __init__(
        self,
        path: Path | str = settings.vector_db_path,
        collection_name: str = settings.vector_collection_name,
        vector_size: int | None = None,
    ):
        self._lock = threading.RLock()
        self._path = Path(path)
        self._vector_size = vector_size or settings.vector_size
        self.db = lancedb.connect(str(self._path))
        self.collection_name = collection_name
        self.ensure_collection()

    def ensure_collection(self):
        """Ensure the table exists with the correct vector size.

        If the table already exists but was created with a different vector
        size (e.g. a previous model was active), it is dropped and recreated so
        that inserts and searches don't fail with shape-mismatch errors.
        """
        with self._lock:
            try:
                existing_tables = self.db.list_tables()

                if self.collection_name in existing_tables:
                    table = self.db.open_table(self.collection_name)
                    schema = table.schema
                    vec_field = schema.field("vector")
                    existing_size = vec_field.type.list_size
                    if existing_size != self._vector_size:
                        logger.warning(
                            "Table %s has vector size %d but model expects %d — recreating",
                            self.collection_name,
                            existing_size,
                            self._vector_size,
                        )
                        self.db.drop_table(self.collection_name)
                    else:
                        logger.info(
                            "Table %s already exists (size=%d)",
                            self.collection_name,
                            existing_size,
                        )
                        self._table = table
                        return

                logger.info(
                    "Creating LanceDB table: %s (size=%d)",
                    self.collection_name,
                    self._vector_size,
                )
                self._table = self.db.create_table(
                    self.collection_name,
                    schema=_table_schema(self._vector_size),
                    exist_ok=True,
                )
                logger.info("Table %s created successfully", self.collection_name)
            except Exception as e:
                logger.error("Error ensuring table exists: %s", e)
                raise

    def delete_collection(self):
        """Delete the entire table (use with caution)."""
        with self._lock:
            try:
                self.db.drop_table(self.collection_name)
                logger.info("Table %s deleted successfully", self.collection_name)
            except Exception as e:
                logger.error("Error deleting table: %s", e)
                raise

    def add_image_embedding(
        self, image_id: int, embedding: list[float], metadata: dict | None = None
    ) -> bool:
        """Add or update an image embedding in LanceDB."""
        with self._lock:
            try:
                payload = metadata or {}
                row = {
                    "id": image_id,
                    "vector": embedding,
                    "image_id": image_id,
                    "filename": payload.get("filename", ""),
                    "author": payload.get("author", ""),
                    "base_name": payload.get("base_name", ""),
                }

                self._table.merge_insert(
                    "id"
                ).when_matched_update_all().when_not_matched_insert_all().execute([row])
                logger.debug("Added embedding for image_id=%s", image_id)
                return True
            except Exception as e:
                logger.error("Error adding embedding for image_id=%s: %s", image_id, e)
                return False

    def batch_add_embeddings(self, items: list[dict]) -> bool:
        """Add or update multiple image embeddings in a single call."""
        with self._lock:
            try:
                rows = []
                for item in items:
                    payload = item.get("metadata", {})
                    rows.append(
                        {
                            "id": item["image_id"],
                            "vector": item["embedding"],
                            "image_id": item["image_id"],
                            "filename": payload.get("filename", ""),
                            "author": payload.get("author", ""),
                            "base_name": payload.get("base_name", ""),
                        }
                    )

                self._table.merge_insert(
                    "id"
                ).when_matched_update_all().when_not_matched_insert_all().execute(rows)
                logger.debug("Batch added %s embeddings to LanceDB", len(rows))
                return True
            except Exception as e:
                logger.error("Error batch adding embeddings: %s", e)
                return False

    def search_similar(
        self,
        query_embedding: list[float],
        limit: int = 100,
        score_threshold: float | None = None,
    ) -> list[dict]:
        """Search for similar images by embedding.

        LanceDB returns cosine *distance* (0 = identical, 2 = opposite).
        We convert to cosine *similarity* (1 - distance) so that higher
        scores mean more similar results (consistent with search expectations).

        When score_threshold is set, results below the threshold are discarded
        after retrieval.  This may return fewer than ``limit`` results — the
        same semantics as Qdrant's score_threshold parameter.  Callers already
        compensate by requesting inflated limits (e.g. limit * 3).
        """
        table = self._table
        if table is None:
            raise RuntimeError("LanceDBService is closed")
        try:
            results = table.search(query_embedding).metric("cosine").limit(limit).to_list()

            output = []
            for row in results:
                score = 1.0 - row["_distance"]
                if score_threshold is not None and score < score_threshold:
                    continue
                output.append(
                    {
                        "image_id": row["image_id"],
                        "score": score,
                        "metadata": {
                            "image_id": row["image_id"],
                            "filename": row["filename"],
                            "author": row["author"],
                            "base_name": row["base_name"],
                        },
                    }
                )

            return output
        except Exception as e:
            logger.error("Error searching similar images: %s", e)
            return []

    def delete_image_embedding(self, image_id: int) -> bool:
        """Delete an image embedding from LanceDB."""
        with self._lock:
            try:
                self._table.delete(f"id = {image_id}")
                logger.debug("Deleted embedding for image_id=%s", image_id)
                return True
            except Exception as e:
                logger.error("Error deleting embedding for image_id=%s: %s", image_id, e)
                return False

    def delete_embeddings(self, image_ids: list[int]) -> bool:
        """Delete embeddings for multiple image IDs from LanceDB in one operation."""
        if not image_ids:
            return True
        with self._lock:
            try:
                ids_str = ", ".join(str(i) for i in image_ids)
                self._table.delete(f"id IN ({ids_str})")
                logger.info("Deleted %d embedding(s) from LanceDB", len(image_ids))
                return True
            except Exception as e:
                logger.warning("Failed to delete %d embeddings from LanceDB: %s", len(image_ids), e)
                return False

    def get_embedding(self, image_id: int) -> list[float] | None:
        """Retrieve a stored embedding vector for an image."""
        table = self._table
        if table is None:
            raise RuntimeError("LanceDBService is closed")
        try:
            results = table.search().where(f"id = {image_id}").limit(1).to_list()
            if results:
                vec = results[0]["vector"]
                return vec if isinstance(vec, list) else np.array(vec).tolist()
            return None
        except Exception as e:
            logger.warning("Error retrieving embedding for image_id=%s: %s", image_id, e)
            return None

    def get_embeddings(self, image_ids: list[int]) -> dict[int, list[float]]:
        """Retrieve embeddings for multiple images in a single query.

        Returns: dict mapping image_id -> embedding vector (missing IDs are absent).
        """
        if not image_ids:
            return {}
        table = self._table
        if table is None:
            raise RuntimeError("LanceDBService is closed")
        try:
            ids_str = ", ".join(str(i) for i in image_ids)
            results = table.search().where(f"id IN ({ids_str})").limit(len(image_ids)).to_list()
            out = {}
            for row in results:
                vec = row["vector"]
                out[row["image_id"]] = vec if isinstance(vec, list) else np.array(vec).tolist()
            return out
        except Exception as e:
            logger.warning("Error retrieving embeddings for %d ids: %s", len(image_ids), e)
            return {}

    def get_collection_info(self) -> dict:
        """Get information about the collection."""
        table = self._table
        if table is None:
            raise RuntimeError("LanceDBService is closed")
        try:
            count = table.count_rows()
            return {
                "name": self.collection_name,
                "points_count": count,
                "status": "ok",
            }
        except Exception as e:
            logger.error("Error getting collection info: %s", e)
            return {}

    def backup_storage(self, target_dir: Path) -> Path:
        """Copy the LanceDB storage directory for backup."""
        with self._lock:
            dest = target_dir / "lancedb"
            shutil.copytree(str(self._path), str(dest))
            logger.info("LanceDB storage backed up to %s", dest)
            return dest

    def delete_collection_by_name(self, collection_name: str) -> None:
        """Delete a LanceDB table by name.

        Raises ValueError if collection_name matches the active table,
        since deleting the active table would break semantic search.
        """
        if collection_name == self.collection_name:
            raise ValueError(
                f"Cannot delete the active embedding table '{collection_name}'. "
                "Switch to a different model first."
            )
        try:
            self.db.drop_table(collection_name)
            logger.info("Deleted LanceDB table '%s'", collection_name)
        except Exception:
            logger.warning("Failed to delete LanceDB table '%s'", collection_name, exc_info=True)
            raise

    def close(self):
        """Close the underlying connection."""
        with self._lock:
            # LanceDB's Python client doesn't require explicit close,
            # but we clear our reference for consistency.
            self._table = None
            self.db = None


# ---------------------------------------------------------------------------
# Lazy singleton (same pattern as get_image_store / get_clip_service)
# ---------------------------------------------------------------------------

_lancedb_service: LanceDBService | None = None
_init_lock = threading.Lock()


def get_lancedb_service() -> LanceDBService:
    """Return the global LanceDBService singleton (created on first call).

    Uses the active model's embedding dimension so the table is created
    with the correct vector size regardless of the settings default.
    """
    global _lancedb_service
    if _lancedb_service is not None:
        return _lancedb_service
    with _init_lock:
        if _lancedb_service is None:
            from .clip_service import get_effective_model_name
            from .model_download_service import get_collection_name
            from .model_registry import get_model

            model_name = get_effective_model_name()
            model_meta = get_model(model_name) if model_name else None
            collection_name = (
                get_collection_name(model_name) if model_name else settings.vector_collection_name
            )
            vector_size = model_meta["embedding_dim"] if model_meta else settings.vector_size
            _lancedb_service = LanceDBService(
                path=settings.vector_db_path,
                collection_name=collection_name,
                vector_size=vector_size,
            )
    return _lancedb_service


def reload_lancedb_service(collection_name: str, vector_size: int | None = None) -> None:
    """Re-create the LanceDBService singleton with a new collection name.

    Called after a model switch to point LanceDB at the new model's table.
    Holds _init_lock to prevent races with concurrent callers and closes the
    old service before replacing it to avoid resource leaks.

    vector_size must be provided when the new model's embedding dimension differs
    from settings.vector_size (e.g. switching from small/512 to medium/768).
    """
    global _lancedb_service
    with _init_lock:
        old_service = _lancedb_service
        _lancedb_service = None
        if old_service is not None:
            old_service.close()
        _lancedb_service = LanceDBService(
            path=settings.vector_db_path,
            collection_name=collection_name,
            vector_size=vector_size or settings.vector_size,
        )
    logger.info("LanceDB service reloaded for table '%s'", collection_name)


def shutdown_lancedb_service() -> None:
    """Close and discard the global LanceDBService singleton."""
    global _lancedb_service
    with _init_lock:
        if _lancedb_service is not None:
            _lancedb_service.close()
            _lancedb_service = None
