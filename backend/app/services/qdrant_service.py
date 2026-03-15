"""Qdrant vector database service (embedded local mode).

Uses QdrantClient(path=...) so Qdrant runs in-process — no Docker container
needed.  A threading.RLock serialises write operations (upsert, delete,
collection management).  Read operations (search, retrieve) run lock-free
since Qdrant's embedded Rust backend is thread-safe for concurrent reads.
"""

import logging
import shutil
import threading
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointIdsList, PointStruct, VectorParams

from ..config import settings

logger = logging.getLogger(__name__)


class QdrantService:
    """Thread-safe Qdrant service backed by local/embedded storage."""

    def __init__(
        self,
        path: Path | str = settings.qdrant_path,
        collection_name: str = settings.qdrant_collection_name,
        vector_size: int | None = None,
    ):
        self._lock = threading.RLock()
        self._path = Path(path)
        self._vector_size = vector_size or settings.qdrant_vector_size
        self.client = QdrantClient(path=str(self._path))
        self.collection_name = collection_name
        self.ensure_collection()

    def ensure_collection(self):
        """Ensure the collection exists with the correct vector size.

        If the collection already exists but was created with a different vector
        size (e.g. a previous model was active), it is dropped and recreated so
        that upserts and searches don't fail with shape-mismatch errors.
        """
        with self._lock:
            try:
                collections = self.client.get_collections().collections
                collection_names = [c.name for c in collections]

                if self.collection_name in collection_names:
                    info = self.client.get_collection(self.collection_name)
                    existing_size = info.config.params.vectors.size
                    if existing_size != self._vector_size:
                        logger.warning(
                            "Collection %s has vector size %d but model expects %d — recreating",
                            self.collection_name,
                            existing_size,
                            self._vector_size,
                        )
                        self.client.delete_collection(self.collection_name)
                        collection_names = []  # force creation below
                    else:
                        logger.info(
                            "Collection %s already exists (size=%d)",
                            self.collection_name,
                            existing_size,
                        )

                if self.collection_name not in collection_names:
                    logger.info(
                        "Creating Qdrant collection: %s (size=%d)",
                        self.collection_name,
                        self._vector_size,
                    )
                    self.client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=VectorParams(
                            size=self._vector_size,
                            distance=Distance.COSINE,
                        ),
                    )
                    logger.info("Collection %s created successfully", self.collection_name)
            except Exception as e:
                logger.error("Error ensuring collection exists: %s", e)
                raise

    def delete_collection(self):
        """Delete the entire collection (use with caution)."""
        with self._lock:
            try:
                self.client.delete_collection(collection_name=self.collection_name)
                logger.info("Collection %s deleted successfully", self.collection_name)
            except Exception as e:
                logger.error("Error deleting collection: %s", e)
                raise

    def add_image_embedding(
        self, image_id: int, embedding: list[float], metadata: dict | None = None
    ) -> bool:
        """Add or update an image embedding in Qdrant."""
        with self._lock:
            try:
                payload = metadata or {}
                payload["image_id"] = image_id

                point = PointStruct(
                    id=image_id,
                    vector=embedding,
                    payload=payload,
                )

                self.client.upsert(
                    collection_name=self.collection_name,
                    points=[point],
                )
                logger.debug("Added embedding for image_id=%s", image_id)
                return True
            except Exception as e:
                logger.error("Error adding embedding for image_id=%s: %s", image_id, e)
                return False

    def batch_add_embeddings(self, items: list[dict]) -> bool:
        """Add or update multiple image embeddings in a single call."""
        with self._lock:
            try:
                points = []
                for item in items:
                    payload = item.get("metadata", {}).copy()
                    payload["image_id"] = item["image_id"]
                    points.append(
                        PointStruct(
                            id=item["image_id"],
                            vector=item["embedding"],
                            payload=payload,
                        )
                    )

                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                )
                logger.debug("Batch added %s embeddings to Qdrant", len(points))
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
        """Search for similar images by embedding (lock-free, read-only)."""
        try:
            results = self.client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                limit=limit,
                score_threshold=score_threshold,
            )

            return [
                {
                    "image_id": point.id,
                    "score": point.score,
                    "metadata": point.payload,
                }
                for point in results.points
            ]
        except Exception as e:
            logger.error("Error searching similar images: %s", e)
            return []

    def delete_image_embedding(self, image_id: int) -> bool:
        """Delete an image embedding from Qdrant."""
        with self._lock:
            try:
                self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=[image_id],
                )
                logger.debug("Deleted embedding for image_id=%s", image_id)
                return True
            except Exception as e:
                logger.error("Error deleting embedding for image_id=%s: %s", image_id, e)
                return False

    def delete_embeddings(self, image_ids: list[int]) -> bool:
        """Delete embeddings for multiple image IDs from Qdrant in one operation."""
        if not image_ids:
            return True
        with self._lock:
            try:
                self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=PointIdsList(points=image_ids),
                )
                logger.info("Deleted %d embedding(s) from Qdrant", len(image_ids))
                return True
            except Exception as e:
                logger.warning("Failed to delete %d embeddings from Qdrant: %s", len(image_ids), e)
                return False

    def get_embedding(self, image_id: int) -> list[float] | None:
        """Retrieve a stored embedding vector for an image (lock-free, read-only)."""
        try:
            results = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[image_id],
                with_vectors=True,
            )
            if results and results[0].vector:
                return results[0].vector
            return None
        except Exception as e:
            logger.warning("Error retrieving embedding for image_id=%s: %s", image_id, e)
            return None

    def get_embeddings(self, image_ids: list[int]) -> dict[int, list[float]]:
        """Retrieve embeddings for multiple images in a single RPC call.

        Returns: dict mapping image_id → embedding vector (missing IDs are absent).
        """
        if not image_ids:
            return {}
        try:
            points = self.client.retrieve(
                collection_name=self.collection_name,
                ids=image_ids,
                with_vectors=True,
            )
            return {p.id: p.vector for p in points if p.vector is not None}
        except Exception as e:
            logger.warning("Error retrieving embeddings for %d ids: %s", len(image_ids), e)
            return {}

    def get_collection_info(self) -> dict:
        """Get information about the collection (lock-free, read-only)."""
        try:
            info = self.client.get_collection(collection_name=self.collection_name)
            return {
                "name": self.collection_name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status,
            }
        except Exception as e:
            logger.error("Error getting collection info: %s", e)
            return {}

    def backup_storage(self, target_dir: Path) -> Path:
        """Copy the Qdrant storage directory for backup."""
        with self._lock:
            dest = target_dir / "qdrant_local"
            shutil.copytree(str(self._path), str(dest))
            logger.info("Qdrant storage backed up to %s", dest)
            return dest

    def delete_collection_by_name(self, collection_name: str) -> None:
        """Delete a Qdrant collection by name.

        Raises ValueError if collection_name matches the active collection,
        since deleting the active collection would break semantic search.
        """
        if collection_name == self.collection_name:
            raise ValueError(
                f"Cannot delete the active embedding collection '{collection_name}'. "
                "Switch to a different model first."
            )
        try:
            self.client.delete_collection(collection_name)
            logger.info("Deleted Qdrant collection '%s'", collection_name)
        except Exception:
            logger.warning(
                "Failed to delete Qdrant collection '%s'", collection_name, exc_info=True
            )
            raise

    def close(self):
        """Close the underlying client."""
        with self._lock:
            self.client.close()


# ---------------------------------------------------------------------------
# Lazy singleton (same pattern as get_image_store / get_clip_service)
# ---------------------------------------------------------------------------

_qdrant_service: QdrantService | None = None
_init_lock = threading.Lock()


def get_qdrant_service() -> QdrantService:
    """Return the global QdrantService singleton (created on first call).

    Uses the active model's embedding dimension so the collection is created
    with the correct vector size regardless of the settings default.
    """
    global _qdrant_service
    if _qdrant_service is not None:
        return _qdrant_service
    with _init_lock:
        if _qdrant_service is None:
            from .clip_service import get_effective_model_name
            from .model_download_service import get_collection_name
            from .model_registry import get_model

            model_name = get_effective_model_name()
            model_meta = get_model(model_name) if model_name else None
            collection_name = (
                get_collection_name(model_name) if model_name else settings.qdrant_collection_name
            )
            vector_size = model_meta["embedding_dim"] if model_meta else settings.qdrant_vector_size
            _qdrant_service = QdrantService(
                path=settings.qdrant_path,
                collection_name=collection_name,
                vector_size=vector_size,
            )
    return _qdrant_service


def reload_qdrant_service(collection_name: str, vector_size: int | None = None) -> None:
    """Re-create the QdrantService singleton with a new collection name.

    Called after a model switch to point Qdrant at the new model's collection.
    Holds _init_lock to prevent races with concurrent callers and closes the
    old service before replacing it to avoid file-handle leaks.

    vector_size must be provided when the new model's embedding dimension differs
    from settings.qdrant_vector_size (e.g. switching from small/512 to medium/768).
    """
    global _qdrant_service
    with _init_lock:
        old_service = _qdrant_service
        _qdrant_service = None
        if old_service is not None:
            old_service.close()
        _qdrant_service = QdrantService(
            path=settings.qdrant_path,
            collection_name=collection_name,
            vector_size=vector_size or settings.qdrant_vector_size,
        )
    logger.info("Qdrant service reloaded for collection '%s'", collection_name)


def shutdown_qdrant_service() -> None:
    """Close and discard the global QdrantService singleton."""
    global _qdrant_service
    if _qdrant_service is not None:
        _qdrant_service.close()
        _qdrant_service = None
