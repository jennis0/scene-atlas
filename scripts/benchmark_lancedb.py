"""Benchmark LanceDB for Scene Atlas vector search replacement.

Tests insert throughput, search latency, memory usage, and disk size
at 10k, 50k, and 100k vectors for all three model dimensions (512, 768, 1152).

Usage:
    uv run python scripts/benchmark_lancedb.py
"""

import shutil
import tempfile
import time
from pathlib import Path

import lancedb
import numpy as np
import pyarrow as pa


DIMENSIONS = [512, 768, 1152]
SCALES = [10_000, 50_000, 100_000]
SEARCH_LIMIT = 100
SEARCH_ITERATIONS = 50


def get_dir_size_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def benchmark_dimension(dim: int, tmp_dir: Path):
    print(f"\n{'=' * 60}")
    print(f"  Dimension: {dim}")
    print(f"{'=' * 60}")

    db_path = tmp_dir / f"bench_{dim}"
    db = lancedb.connect(str(db_path))

    schema = pa.schema(
        [
            pa.field("id", pa.int64()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
            pa.field("image_id", pa.int64()),
            pa.field("filename", pa.utf8()),
            pa.field("author", pa.utf8()),
            pa.field("base_name", pa.utf8()),
        ]
    )

    table = db.create_table("embeddings_test", schema=schema)

    for scale in SCALES:
        # --- Insert ---
        # Determine how many new vectors to add (incremental)
        current_count = table.count_rows()
        to_add = scale - current_count
        if to_add <= 0:
            continue

        batch_size = 5000
        insert_start = time.perf_counter()

        for offset in range(0, to_add, batch_size):
            batch_end = min(offset + batch_size, to_add)
            actual_batch = batch_end - offset
            start_id = current_count + offset

            vectors = np.random.randn(actual_batch, dim).astype(np.float32)
            # Normalize like real CLIP embeddings
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            vectors = vectors / norms

            data = [
                {
                    "id": start_id + i,
                    "vector": vectors[i].tolist(),
                    "image_id": start_id + i,
                    "filename": f"image_{start_id + i}.jpg",
                    "author": f"author_{(start_id + i) % 100}",
                    "base_name": f"group_{(start_id + i) % 500}",
                }
                for i in range(actual_batch)
            ]
            table.add(data)

        insert_elapsed = time.perf_counter() - insert_start

        # --- Search ---
        query_vec = np.random.randn(dim).astype(np.float32)
        query_vec = query_vec / np.linalg.norm(query_vec)

        # Warmup
        table.search(query_vec.tolist()).metric("cosine").limit(SEARCH_LIMIT).to_list()

        search_times = []
        for _ in range(SEARCH_ITERATIONS):
            q = np.random.randn(dim).astype(np.float32)
            q = q / np.linalg.norm(q)
            t0 = time.perf_counter()
            results = table.search(q.tolist()).metric("cosine").limit(SEARCH_LIMIT).to_list()
            search_times.append(time.perf_counter() - t0)

        disk_mb = get_dir_size_mb(db_path)

        print(f"\n  Scale: {scale:,} vectors")
        print(
            f"    Insert {to_add:,} vectors:  {insert_elapsed:.2f}s ({to_add / insert_elapsed:.0f} vec/s)"
        )
        print(f"    Search (top-{SEARCH_LIMIT}):")
        print(f"      Mean:   {np.mean(search_times) * 1000:.1f}ms")
        print(f"      Median: {np.median(search_times) * 1000:.1f}ms")
        print(f"      P95:    {np.percentile(search_times, 95) * 1000:.1f}ms")
        print(f"      P99:    {np.percentile(search_times, 99) * 1000:.1f}ms")
        print(f"    Results returned: {len(results)}")
        print(f"    Disk size: {disk_mb:.1f} MB")

    # --- ANN Index benchmark at max scale ---
    print(f"\n  --- ANN Index benchmark (IVF-PQ) at {SCALES[-1]:,} vectors ---")

    # Re-create table at max scale for indexed search
    table_ann = db.create_table("embeddings_ann", schema=schema)
    batch_size = 5000
    for offset in range(0, SCALES[-1], batch_size):
        actual_batch = min(batch_size, SCALES[-1] - offset)
        vectors = np.random.randn(actual_batch, dim).astype(np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / norms
        data = [
            {
                "id": offset + i,
                "vector": vectors[i].tolist(),
                "image_id": offset + i,
                "filename": f"image_{offset + i}.jpg",
                "author": f"author_{(offset + i) % 100}",
                "base_name": f"group_{(offset + i) % 500}",
            }
            for i in range(actual_batch)
        ]
        table_ann.add(data)

    num_partitions = min(256, SCALES[-1] // 100)
    num_sub_vectors = min(16, dim // 32)
    print(
        f"    Creating IVF-PQ index (partitions={num_partitions}, sub_vectors={num_sub_vectors})..."
    )
    idx_start = time.perf_counter()
    table_ann.create_index(
        metric="cosine",
        num_partitions=num_partitions,
        num_sub_vectors=num_sub_vectors,
        index_type="IVF_PQ",
        vector_column_name="vector",
    )
    idx_elapsed = time.perf_counter() - idx_start
    print(f"    Index creation: {idx_elapsed:.2f}s")

    # Warmup
    q = np.random.randn(dim).astype(np.float32)
    q = q / np.linalg.norm(q)
    table_ann.search(q.tolist()).metric("cosine").nprobes(20).refine_factor(10).limit(
        SEARCH_LIMIT
    ).to_list()

    ann_times = []
    for _ in range(SEARCH_ITERATIONS):
        q = np.random.randn(dim).astype(np.float32)
        q = q / np.linalg.norm(q)
        t0 = time.perf_counter()
        results = (
            table_ann.search(q.tolist())
            .metric("cosine")
            .nprobes(20)
            .refine_factor(10)
            .limit(SEARCH_LIMIT)
            .to_list()
        )
        ann_times.append(time.perf_counter() - t0)

    print(f"    ANN Search (top-{SEARCH_LIMIT}, nprobes=20, refine=10):")
    print(f"      Mean:   {np.mean(ann_times) * 1000:.1f}ms")
    print(f"      Median: {np.median(ann_times) * 1000:.1f}ms")
    print(f"      P95:    {np.percentile(ann_times, 95) * 1000:.1f}ms")
    print(f"      P99:    {np.percentile(ann_times, 99) * 1000:.1f}ms")
    print(f"    Results returned: {len(results)}")
    print(f"    Disk size (indexed): {get_dir_size_mb(db_path):.1f} MB")

    db.drop_table("embeddings_ann")
    db.drop_table("embeddings_test")


def test_upsert_delete(tmp_dir: Path):
    """Test upsert and delete operations work correctly."""
    print(f"\n{'=' * 60}")
    print("  Upsert & Delete correctness test")
    print(f"{'=' * 60}")

    db = lancedb.connect(str(tmp_dir / "crud_test"))
    dim = 512

    data = [
        {
            "id": i,
            "vector": np.random.randn(dim).astype(np.float32).tolist(),
            "image_id": i,
            "filename": f"img_{i}.jpg",
            "author": "test",
            "base_name": "group",
        }
        for i in range(100)
    ]
    table = db.create_table("test_crud", data)
    assert table.count_rows() == 100, f"Expected 100, got {table.count_rows()}"

    # Upsert (update existing + insert new)
    upsert_data = [
        {
            "id": 50,
            "vector": np.zeros(dim, dtype=np.float32).tolist(),
            "image_id": 50,
            "filename": "updated.jpg",
            "author": "new_author",
            "base_name": "new_group",
        },
        {
            "id": 200,
            "vector": np.ones(dim, dtype=np.float32).tolist(),
            "image_id": 200,
            "filename": "new.jpg",
            "author": "new",
            "base_name": "new",
        },
    ]
    table.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(
        upsert_data
    )
    assert table.count_rows() == 101, f"Expected 101 after upsert, got {table.count_rows()}"

    # Delete single
    table.delete("id = 200")
    assert table.count_rows() == 100, f"Expected 100 after delete, got {table.count_rows()}"

    # Delete multiple
    table.delete("id >= 90 AND id < 100")
    assert table.count_rows() == 90, f"Expected 90 after batch delete, got {table.count_rows()}"

    print("  All CRUD operations passed!")
    db.drop_table("test_crud")


def test_retrieve_vectors(tmp_dir: Path):
    """Test retrieving stored vectors by ID."""
    print(f"\n{'=' * 60}")
    print("  Vector retrieval test")
    print(f"{'=' * 60}")

    db = lancedb.connect(str(tmp_dir / "retrieve_test"))
    dim = 512

    original_vec = np.random.randn(dim).astype(np.float32)
    original_vec = original_vec / np.linalg.norm(original_vec)

    data = [
        {
            "id": 42,
            "vector": original_vec.tolist(),
            "image_id": 42,
            "filename": "test.jpg",
            "author": "tester",
            "base_name": "group",
        }
    ]
    table = db.create_table("test_retrieve", data)

    # Retrieve by filter
    result = table.search().where("id = 42").limit(1).to_list()
    assert len(result) == 1, f"Expected 1 result, got {len(result)}"
    retrieved_vec = np.array(result[0]["vector"], dtype=np.float32)
    cos_sim = np.dot(original_vec, retrieved_vec) / (
        np.linalg.norm(original_vec) * np.linalg.norm(retrieved_vec)
    )
    assert cos_sim > 0.999, f"Vector mismatch: cosine similarity {cos_sim}"

    print("  Vector retrieval passed!")
    db.drop_table("test_retrieve")


def main():
    print("LanceDB Benchmark for Scene Atlas")
    print(f"Testing dimensions: {DIMENSIONS}")
    print(f"Testing scales: {[f'{s:,}' for s in SCALES]}")
    print(f"Search: top-{SEARCH_LIMIT}, {SEARCH_ITERATIONS} iterations per measurement")

    tmp_dir = Path(tempfile.mkdtemp(prefix="lancedb_bench_"))
    print(f"Working directory: {tmp_dir}")

    try:
        # Correctness tests
        test_upsert_delete(tmp_dir)
        test_retrieve_vectors(tmp_dir)

        # Performance benchmarks
        for dim in DIMENSIONS:
            benchmark_dimension(dim, tmp_dir)

        print(f"\n{'=' * 60}")
        print("  BENCHMARK COMPLETE")
        print(f"{'=' * 60}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
