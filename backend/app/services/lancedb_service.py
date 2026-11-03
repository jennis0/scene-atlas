"""LanceDB vector database service (embedded disk-backed mode).

Uses lancedb.connect(path=...) for memory-mapped disk storage — no separate
server process needed.  The connection's caches are bounded (``_session``).  A threading.RLock serialises write operations (upsert,
delete, table management).  Read operations (search, retrieve) snapshot the
table reference and are safe to call concurrently with writes, but will raise
RuntimeError if called after close().
"""

import logging
import shutil
import threading
from collections.abc import Iterable
from pathlib import Path

import lancedb
import numpy as np
import pyarrow as pa
from lancedb.db import DBConnection
from lancedb.table import Table

from ..config import settings

logger = logging.getLogger(__name__)

# Bounds on the connection's caches (lance's defaults: 1 GiB metadata, 6 GiB index). Every
# write (one per ingest batch of 16) is a new table version whose manifest lists every fragment,
# and the metadata cache keeps them all: about 120 MB after 700 batches (11k images), growing
# quadratically up to the 1 GiB default (design/resource-management.md, "Memory"). Searches scan
# a few tables' fragments, whose metadata fits easily in this; there are no vector indexes.
_METADATA_CACHE_BYTES = 64 * 1024 * 1024
_INDEX_CACHE_BYTES = 64 * 1024 * 1024
# get_embedding_arrays. Filtered lookups take this many ids per ``id IN`` query.
_LOOKUP_MAX_IDS = 500
# A streaming scan (in batches of rows) reads every vector of the table, so it is used for ids
# that are a large share of the table, or many: each filtered query scans every fragment and
# left ~15 MB of native buffers held, so 10 of them already hold more than a scan's batch.
_SCAN_MIN_SHARE = 0.1
_SCAN_MIN_IDS = 10 * _LOOKUP_MAX_IDS
_SCAN_BATCH_ROWS = 4096


def _session() -> lancedb.Session:
    return lancedb.Session(
        index_cache_size_bytes=_INDEX_CACHE_BYTES, metadata_cache_size_bytes=_METADATA_CACHE_BYTES
    )


def _scan_vectors(table: Table, wanted: np.ndarray) -> dict[int, np.ndarray]:
    """The vectors of the ``wanted`` (sorted) image ids, by one streaming scan of the table.
    Rows whose vector is null are skipped: ``FixedSizeListArray.flatten`` would drop their
    slots and misalign every row after them, so rows are cut from ``values`` instead."""
    out: dict[int, np.ndarray] = {}
    query = table.search().select(["image_id", "vector"]).limit(None)
    for batch in query.to_batches(_SCAN_BATCH_ROWS):
        ids = batch.column("image_id").to_numpy(zero_copy_only=False)
        column = batch.column("vector")
        keep = np.isin(ids, wanted)
        if column.null_count:
            keep &= column.is_valid().to_numpy(zero_copy_only=False)
        rows = np.flatnonzero(keep)
        if not len(rows):
            continue
        dim = column.type.list_size
        values = column.values.slice(column.offset * dim, len(column) * dim)
        vectors = values.to_numpy(zero_copy_only=False).reshape(len(column), dim)
        for row in rows.tolist():
            out[int(ids[row])] = np.array(vectors[row], dtype=np.float32)
    return out


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
        path: Path | str,
        collection_name: str,
        vector_size: int | None = None,
    ):
        self._lock = threading.RLock()
        self._path = Path(path)
        self._vector_size = vector_size or settings.vector_size
        self.session = _session()  # its caches, bounded
        self.db: DBConnection | None = lancedb.connect(str(self._path), session=self.session)
        self._table: Table | None = None
        self.collection_name = collection_name
        self.ensure_collection()

    @property
    def _conn(self) -> DBConnection:
        if self.db is None:
            raise RuntimeError("LanceDBService is closed")
        return self.db

    @property
    def _tbl(self) -> Table:
        if self._table is None:
            raise RuntimeError("LanceDBService is closed")
        return self._table

    def table_exists(self, name: str) -> bool:
        # list_tables() is paginated and returns a response object, not a list of names.
        page_token = None
        while True:
            page = self._conn.list_tables(page_token=page_token)
            if name in page.tables:
                return True
            page_token = page.page_token
            if not page_token:
                return False

    def ensure_collection(self):
        """Ensure the table exists with the correct vector size.

        If the table already exists but was created with a different vector
        size (e.g. a previous model was active), it is dropped and recreated so
        that inserts and searches don't fail with shape-mismatch errors.
        """
        with self._lock:
            if self.table_exists(self.collection_name):
                table = self._conn.open_table(self.collection_name)
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
                    self._conn.drop_table(self.collection_name)
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
            self._table = self._conn.create_table(
                self.collection_name,
                schema=_table_schema(self._vector_size),
                exist_ok=True,
            )
            logger.info("Table %s created successfully", self.collection_name)

    def delete_collection(self):
        """Delete the entire table (use with caution)."""
        with self._lock:
            self._conn.drop_table(self.collection_name)
            logger.info("Table %s deleted successfully", self.collection_name)

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

                self._tbl.merge_insert(
                    "id"
                ).when_matched_update_all().when_not_matched_insert_all().execute([row])
                logger.debug("Added embedding for image_id=%s", image_id)
                return True
            except Exception:
                logger.exception("Error adding embedding for image_id=%s", image_id)
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

                self._tbl.merge_insert(
                    "id"
                ).when_matched_update_all().when_not_matched_insert_all().execute(rows)
                logger.debug("Batch added %s embeddings to LanceDB", len(rows))
                return True
            except Exception:
                logger.exception("Error batch adding embeddings")
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
        table = self._tbl
        try:
            # search() is annotated with the base builder; a vector query returns the vector builder.
            query = table.search(query_embedding).distance_type("cosine")  # pyright: ignore[reportAttributeAccessIssue]
            results = query.limit(limit).to_list()

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
        except Exception:
            logger.exception("Error searching similar images")
            return []

    def delete_image_embedding(self, image_id: int) -> bool:
        """Delete an image embedding from LanceDB."""
        with self._lock:
            try:
                self._tbl.delete(f"id = {image_id}")
                logger.debug("Deleted embedding for image_id=%s", image_id)
                return True
            except Exception:
                logger.exception("Error deleting embedding for image_id=%s", image_id)
                return False

    def delete_embeddings(self, image_ids: list[int]) -> bool:
        """Delete embeddings for multiple image IDs from LanceDB in one operation."""
        if not image_ids:
            return True
        with self._lock:
            try:
                ids_str = ", ".join(str(i) for i in image_ids)
                self._tbl.delete(f"id IN ({ids_str})")
                logger.info("Deleted %d embedding(s) from LanceDB", len(image_ids))
                return True
            except Exception as e:
                logger.warning("Failed to delete %d embeddings from LanceDB: %s", len(image_ids), e)
                return False

    def get_embedding(self, image_id: int) -> list[float] | None:
        """Retrieve a stored embedding vector for an image."""
        table = self._tbl
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
        table = self._tbl
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

    def get_embedding_arrays(self, image_ids: Iterable[int]) -> dict[int, np.ndarray]:
        """float32 vectors of many images (missing ids, and rows without a vector, are absent).

        Few ids are looked up by ``id IN (...)`` filters of ``_LOOKUP_MAX_IDS``. Each such
        query scans every fragment, and after a 10k-id lookup (20 queries) ~300 MB of native
        buffers stayed held, so ids that are many (``_SCAN_MIN_IDS``) or a large share of the
        table (``_SCAN_MIN_SHARE``) are read by one streaming scan of ``(image_id, vector)``
        instead, holding one batch at a time; a scan that fails twice falls back to the
        filtered queries, so one error doesn't make every vector missing.
        """
        table = self._tbl  # a closed service raises here, as get_embeddings does
        wanted = np.unique(np.fromiter(image_ids, dtype=np.int64))
        if len(wanted) == 0:
            return {}
        if self._scan_pays(table, len(wanted)):
            for attempt in (1, 2):
                try:
                    return _scan_vectors(table, wanted)
                except Exception as e:
                    logger.warning(
                        "Error scanning embeddings for %d ids (attempt %d): %s",
                        len(wanted),
                        attempt,
                        e,
                    )
        out: dict[int, np.ndarray] = {}
        ids = wanted.tolist()
        for start in range(0, len(ids), _LOOKUP_MAX_IDS):
            found = self.get_embeddings(ids[start : start + _LOOKUP_MAX_IDS])
            out.update(
                (i, np.asarray(v, dtype=np.float32)) for i, v in found.items() if v is not None
            )
        return out

    @staticmethod
    def _scan_pays(table: Table, n_ids: int) -> bool:
        """Whether ``n_ids`` are read by a scan rather than filtered queries."""
        if n_ids <= _LOOKUP_MAX_IDS:
            return False
        if n_ids >= _SCAN_MIN_IDS:
            return True
        try:
            rows = table.count_rows()
        except Exception:
            return False
        return n_ids >= _SCAN_MIN_SHARE * rows

    def get_all_ids(self) -> set[int]:
        """Every image id in the table, without loading vectors (for reconciliation)."""
        table = self._tbl
        rows = table.search().select(["id"]).limit(None).to_arrow()
        return set(rows.column("id").to_pylist())

    def get_collection_info(self) -> dict:
        """Get information about the collection."""
        table = self._tbl
        try:
            count = table.count_rows()
            return {
                "name": self.collection_name,
                "points_count": count,
                "status": "ok",
            }
        except Exception:
            logger.exception("Error getting collection info")
            return {}

    def row_count(self, collection_name: str) -> int | None:
        """Rows in *collection_name*, or None if the table doesn't exist."""
        if not self.table_exists(collection_name):
            return None
        return self._conn.open_table(collection_name).count_rows()

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
            self._conn.drop_table(collection_name)
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


# Lazy singleton (same pattern as get_image_store / get_clip_service)

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
            model_meta = get_model(model_name)
            vector_size = model_meta["embedding_dim"] if model_meta else settings.vector_size
            _lancedb_service = LanceDBService(
                path=settings.vector_db_path,
                collection_name=get_collection_name(model_name),
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
