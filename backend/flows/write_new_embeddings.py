from pathlib import Path

from prefect import task, flow
from tqdm import tqdm

from backend.app.config import settings
from backend.app.services.clip_service import CLIPService
from backend.app.services import ImageStore, QdrantService, get_image_store
from backend.app.models import get_engine, get_session_local, Image


def create_qdrant_data(
    embedding: list[float], image_id: int, filename: str, author: str, base_name: str
) -> dict:
    return {
        "image_id": image_id,
        "embedding": embedding,
        "metadata": {
            "filename": filename,
            "author": author,
            "base_name": base_name,
        },
    }


@task(name="write_embeddings_batch")
def generate_embeddings(images: list[Image], model_name: str, collection_name: str):
    qdrant = QdrantService(collection_name=collection_name)
    qdrant.ensure_collection()
    print("Retrieved Qdrant collection")

    clip_service = CLIPService(model_name=model_name)
    image_store = get_image_store()

    print("Loaded CLIP model")

    batch_size = 100
    result = True
    for i in range(0, len(images), batch_size):
        print(f"Starting batch {i // batch_size + 1} of {len(images) // batch_size + 1}")
        batch_images = images[i : i + batch_size]
        embeddings = [
            clip_service.encode_image(image_store.get_path(image["storage_key"]))
            for image in tqdm(batch_images)
        ]

        qdrant_prep = [
            create_qdrant_data(
                embedding,
                image["id"],
                image["filename"],
                image["author"],
                image["variant_group_name"],
            )
            for embedding, image in zip(embeddings, batch_images)
        ]
        result &= qdrant.batch_add_embeddings(qdrant_prep)
        print(f"Batch {i // batch_size + 1} Write Result: {result}")

    return result


@task(name="fetch_images_from_db")
def get_all_images() -> list[Image]:

    engine = get_engine(settings.database_url)
    SessionLocal = get_session_local(engine)
    db = SessionLocal()

    skip = 0
    batch = 1000
    print("Fetching images from database...")

    images = []
    while True:
        new_images = db.query(Image).offset(skip).limit(batch).all()

        if not new_images:
            break

        skip += batch
        images += [
            {
                "id": image.id,
                "storage_key": image.storage_key,
                "filename": image.filename,
                "author": image.author,
                "variant_group_name": image.variant_group_name,
            }
            for image in new_images
        ]

    print(f"Total images fetched: {len(images)}")
    return images


@flow(name="write_new_embeddings_flow", log_prints=True)
def write_new_embeddings(
    model_name: str = settings.clip_model_name,
    collection_name: str = settings.qdrant_collection_name,
):
    images = get_all_images()
    result = generate_embeddings(images, model_name, collection_name)
    return result


if __name__ == "__main__":
    write_new_embeddings()
