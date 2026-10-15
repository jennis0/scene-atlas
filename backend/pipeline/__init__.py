"""Image processing pipeline: ingest, maintenance, and backfill functions.

The ingest pipeline (ADR-018) lives in ``ingest_queue`` (durable item/job
operations), ``ingest_process`` (one batch), ``ingest_worker`` (the worker
loop), ``ingest_archive`` and ``ingest_maintenance``.
"""
