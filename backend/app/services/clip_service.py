"""CLIP model service for generating image and text embeddings."""

import logging
from pathlib import Path
from typing import List, Union

import torch
from PIL import Image

from ..config import settings

logger = logging.getLogger(__name__)


class CLIPService:
    """Service for generating CLIP embeddings."""

    def __init__(self, device: str = settings.clip_device,
                 model_name: str = settings.clip_model_name):
        """Initialize CLIP model and processor.

        The transformers import is deferred to here rather than module level.
        On Windows, newer transformers versions scan their own directory tree at
        import time and hit an OSError (EINVAL) on certain files.  Prefect loads
        the flow module on every flow-run startup, so a top-level transformers
        import would crash every flow before any work begins.  Keeping it lazy
        means only processes that actually instantiate CLIPService pay the cost.
        """
        from transformers import CLIPModel, CLIPProcessor

        logger.info(f"Loading CLIP model: {model_name}")
        self.device = device
        self.model_name = model_name

        # Try loading from local cache first to avoid HTTP requests on every startup.
        # Falls back to downloading if the model isn't cached yet.
        try:
            self.model = CLIPModel.from_pretrained(
                self.model_name, local_files_only=True
            ).to(self.device)
            self.processor = CLIPProcessor.from_pretrained(
                self.model_name, local_files_only=True
            )
            logger.info("CLIP model loaded from local cache")
        except OSError:
            logger.info("CLIP model not cached locally, downloading...")
            self.model = CLIPModel.from_pretrained(self.model_name).to(self.device)
            self.processor = CLIPProcessor.from_pretrained(self.model_name)

        self.model.eval()
        logger.info(f"CLIP model ready on device: {self.device}")

    def encode_image(self, image_path: Union[str, Path]) -> List[float]:
        """Generate embedding for an image.

        Args:
            image_path: Path to the image file

        Returns:
            Embedding vector as list of floats
        """
        try:
            # Load and preprocess image — use context manager so PIL frees pixel data
            with Image.open(image_path) as img:
                image = img.convert("RGB")
            inputs = self.processor(images=image, return_tensors="pt")
            del image  # free after processor has extracted tensors

            # Move tensors to device individually (Windows compatibility)
            inputs = {k: v.to(self.device) if hasattr(v, 'to') else v for k, v in inputs.items()}

            # Generate embedding
            with torch.no_grad():
                vision_outputs = self.model.vision_model(**inputs)
                pooled_output = vision_outputs.pooler_output
                image_features = self.model.visual_projection(pooled_output)
                image_features = torch.nn.functional.normalize(image_features, p=2, dim=-1)

            embedding = image_features.cpu().numpy().flatten().tolist()
            logger.debug(f"Generated embedding for {image_path}, size: {len(embedding)}")
            return embedding

        except Exception as e:
            logger.error(f"Error encoding image {image_path}: {e}")
            raise

    def encode_text(self, text: str) -> List[float]:
        """Generate embedding for text query.

        Args:
            text: Text query (e.g., "dark forest cave with water")

        Returns:
            Embedding vector as list of floats
        """
        try:
            inputs = self.processor(text=text, return_tensors="pt", padding=True)
            inputs = {k: v.to(self.device) if hasattr(v, 'to') else v for k, v in inputs.items()}

            with torch.no_grad():
                text_outputs = self.model.text_model(**inputs)
                pooled_output = text_outputs.pooler_output
                text_features = self.model.text_projection(pooled_output)
                text_features = torch.nn.functional.normalize(text_features, p=2, dim=-1)

            embedding = text_features.cpu().numpy().flatten().tolist()
            logger.debug(f"Generated text embedding for '{text}', size: {len(embedding)}")
            return embedding

        except Exception as e:
            logger.error(f"Error encoding text '{text}': {e}")
            raise

    def batch_encode_images(self, image_paths: List[Union[str, Path]]) -> List[List[float]]:
        """Generate embeddings for multiple images in batch.

        Args:
            image_paths: List of paths to image files

        Returns:
            List of embedding vectors
        """
        try:
            # Load and preprocess images — close originals immediately after convert
            images = []
            for path in image_paths:
                with Image.open(path) as img:
                    images.append(img.convert("RGB"))
            inputs = self.processor(images=images, return_tensors="pt", padding=True)
            del images  # free PIL objects after processor has extracted tensors

            inputs = {k: v.to(self.device) if hasattr(v, 'to') else v for k, v in inputs.items()}

            with torch.no_grad():
                vision_outputs = self.model.vision_model(**inputs)
                pooled_outputs = vision_outputs.pooler_output
                image_features = self.model.visual_projection(pooled_outputs)
                image_features = torch.nn.functional.normalize(image_features, p=2, dim=-1)

            embeddings = image_features.cpu().numpy().tolist()
            logger.debug(f"Generated batch embeddings for {len(image_paths)} images")
            return embeddings

        except Exception as e:
            logger.error(f"Error batch encoding images: {e}")
            raise


# Global instance (lazy loaded)
_clip_service: Union[CLIPService, None] = None


def get_clip_service() -> CLIPService:
    """Get or create CLIP service instance (singleton)."""
    global _clip_service
    if _clip_service is None:
        _clip_service = CLIPService()
    return _clip_service
