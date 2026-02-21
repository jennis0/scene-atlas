from backend.app.config import settings
from backend.app.services.clip_service import CLIPService
from backend.app.services import ImageStore, QdrantService, get_image_store
from backend.app.models import get_engine, get_session_local, Image

from prefect import task, flow
from pathlib import Path

from tqdm import tqdm

PROJECT_ROOT = str(Path(__file__).parent.parent)


def create_qdrant_data(embedding: list[float], image_id: int, filename: str, author: str, base_name: str) -> dict:
    return {
        "image_id": image_id,
        "embedding": embedding,
        "metadata": {
            "filename": filename,
            "author": author,
            "base_name": base_name,
        }
    }

@task(name="write_embeddings_batch")
def generate_embeddings(images: list[Image], image_store: ImageStore, qdrant: QdrantService, model_name: str):
    
    clip_service = CLIPService(model_name=model_name)
    embeddings = [clip_service.encode_image(image_store.get_path(image.storage_key)) for image in tqdm(images)]
    
    batch_size = 100
    for i in range(0, len(embeddings), batch_size):
        batch_embeddings = embeddings[i:i + batch_size]
        batch_images = images[i:i + batch_size]
        qdrant_prep = [create_qdrant_data(embedding, image.id, image.filename, 
                                        image.author, image.variant_group_name) 
                    for embedding, image in zip(batch_embeddings, batch_images)]
        result = qdrant.batch_add_embeddings(qdrant_prep)
        print(f"Batch {i//batch_size + 1} Write Result: {result}")

@flow(name="write_new_embeddings_flow")
def write_new_embeddings(model_name: str = settings.clip_model_name,
                         collection_name: str = settings.qdrant_collection_name):
    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()
    
    image_store = get_image_store()
    
    qdrant = QdrantService(collection_name=collection_name)
    print(qdrant.collection_name)
    qdrant.ensure_collection()
    print(qdrant.get_collection_info())

    skip = 0
    batch = 1000
    images = db.query(Image).offset(skip).limit(batch).all()
    
    while images:
        skip += batch
        images += db.query(Image).offset(skip).limit(batch).all()
    
    write_batch(images, image_store, qdrant, model_name)