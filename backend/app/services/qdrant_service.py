"""Qdrant vector database service."""

import logging
from typing import List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from ..config import settings

logger = logging.getLogger(__name__)


class QdrantService:
    """Service for interacting with Qdrant vector database."""

    def __init__(self, 
                 host: str = settings.qdrant_host,
                 port: int = settings.qdrant_port,
                 collection_name: str = settings.qdrant_collection_name
        ):
        """Initialize Qdrant client."""
        self.client = QdrantClient(
            host=host,
            port=port,
        )
        self.collection_name = collection_name
        self.ensure_collection()

    def delete_collection(self):
        """Delete the entire collection (use with caution)."""
        try:
            self.client.delete_collection(collection_name=self.collection_name)
            logger.info(f"Collection {self.collection_name} deleted successfully")
        except Exception as e:
            logger.error(f"Error deleting collection: {e}")
            raise

    def ensure_collection(self):
        """Ensure the collection exists, create if not."""
        try:
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.collection_name not in collection_names:
                logger.info(f"Creating Qdrant collection: {self.collection_name}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=settings.qdrant_vector_size,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Collection {self.collection_name} created successfully")
            else:
                logger.info(f"Collection {self.collection_name} already exists")
        except Exception as e:
            logger.error(f"Error ensuring collection exists: {e}")
            raise

    def add_image_embedding(
        self,
        image_id: int,
        embedding: List[float],
        metadata: Optional[dict] = None
    ) -> bool:
        """Add or update an image embedding in Qdrant.

        Args:
            image_id: Unique image ID (from SQLite)
            embedding: CLIP embedding vector
            metadata: Optional metadata (filename, etc.)

        Returns:
            True if successful
        """
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
            logger.debug(f"Added embedding for image_id={image_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding embedding for image_id={image_id}: {e}")
            return False

    def batch_add_embeddings(
        self,
        items: List[dict],
    ) -> bool:
        """Add or update multiple image embeddings in Qdrant in a single call.

        Args:
            items: List of dicts with 'image_id', 'embedding', and optional 'metadata'

        Returns:
            True if successful
        """
        try:
            points = []
            for item in items:
                payload = item.get("metadata", {}).copy()
                payload["image_id"] = item["image_id"]
                points.append(PointStruct(
                    id=item["image_id"],
                    vector=item["embedding"],
                    payload=payload,
                ))

            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
            )
            logger.debug(f"Batch added {len(points)} embeddings to Qdrant")
            return True
        except Exception as e:
            logger.error(f"Error batch adding embeddings: {e}")
            return False

    def search_similar(
        self,
        query_embedding: List[float],
        limit: int = 100,
        score_threshold: Optional[float] = None,
    ) -> List[dict]:
        """Search for similar images by embedding.

        Args:
            query_embedding: Query vector (CLIP embedding)
            limit: Maximum number of results
            score_threshold: Minimum similarity score (0.0-1.0)

        Returns:
            List of results with image_id and score
        """
        try:
            # Use query_points (the correct method in newer qdrant-client)
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
            logger.error(f"Error searching similar images: {e}")
            return []

    def delete_image_embedding(self, image_id: int) -> bool:
        """Delete an image embedding from Qdrant.

        Args:
            image_id: Image ID to delete

        Returns:
            True if successful
        """
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=[image_id],
            )
            logger.debug(f"Deleted embedding for image_id={image_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting embedding for image_id={image_id}: {e}")
            return False

    def get_collection_info(self) -> dict:
        """Get information about the collection.

        Returns:
            Collection statistics
        """
        try:
            info = self.client.get_collection(collection_name=self.collection_name)
            return {
                "name": self.collection_name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status,
            }
        except Exception as e:
            logger.error(f"Error getting collection info: {e}")
            return {}


# Global instance
qdrant_service = QdrantService()
