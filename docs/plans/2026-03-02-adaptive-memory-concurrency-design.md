# Adaptive Memory-Aware Concurrency — Design

**Date:** 2026-03-02
**Status:** Approved
**Area:** Import pipeline / ingestion

---

## Problem

The import pipeline runs prepare workers (thumbnail generation, grid detection, color extraction) in a fixed `ThreadPoolExecutor` with up to 4 concurrent workers. Grid detection loads images at full resolution before downsampling — a single 8K battlemap can spike to ~400 MB before the pixels are released. With 4 workers and the CLIP model's ~600 MB resident footprint, a constrained machine (4–8 GB RAM) reliably OOM-kills the process mid-import.

The batch size (16) and concurrency (4) are static values from `PipelineConfig`, with no awareness of how much memory is actually free at runtime.

---

## Goals

- Prevent OOM kills across a range of hardware (targeting general Electron users with 4–16 GB RAM)
- Maintain parallelisation benefits — don't simply hard-code 1 worker
- Handle multiple simultaneous import jobs fairly
- Be observable: log whenever concurrency changes and why
- Pause and retry rather than crash when memory is critically low

---

## Approach

**Per-batch adaptive concurrency via psutil.**

At the top of each batch iteration, query `psutil.virtual_memory().available` and compute:

```
effective_workers = max(1, min(configured_max, budget_mb // (per_worker_mb × active_jobs)))

where:
  budget_mb     = available_mb - safety_reserve_mb
  active_jobs   = count of running import jobs in JobRunner
```

The `ThreadPoolExecutor` is already re-created per batch (inside a `with` block in the loop), so changing `max_workers` between batches requires no architectural change.

When `available_mb < safety_reserve_mb + per_worker_mb` (too low even for a single worker), the pipeline pauses and polls until memory frees or a timeout expires, then proceeds with 1 worker regardless.

### Why `psutil.virtual_memory().available`?

- `available` is system-level free memory and already **excludes** our own process's RSS — the CLIP model's ~600 MB does not need to be subtracted again
- Cross-platform (Linux, macOS, Windows) — required for Electron deployment
- The existing `resource.getrusage(RUSAGE_SELF).ru_maxrss` only measures our own RSS; it cannot tell us how much the OS has left to give

### Multiple concurrent jobs

`process_import_job` queries `JobRunner` for the count of currently running import jobs and passes it into `_run_group` as `active_jobs`. Each job divides the available budget by `active_jobs`, so two simultaneous imports each assume they get half. No inter-process locking required.

---

## Configuration Parameters

Added to `PipelineConfig` (not exposed via AppSettings/DB in this iteration — can be promoted later):

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `memory_per_prepare_worker_mb` | 400 | Estimated peak RAM per prepare worker |
| `memory_safety_reserve_mb` | 500 | OS headroom — never allocate into this |
| `memory_wait_timeout_s` | 120 | Max seconds to wait when critically low |
| `memory_wait_poll_s` | 10 | Poll interval while waiting |

### Calibration rationale

- **400 MB per worker**: grid detection loads full-res image (up to ~320 MB for 8K battlemaps) then downsamples; thumbnails add transient overhead. Conservative upper bound.
- **500 MB reserve**: OS + file-system cache headroom. `available` already accounts for our process footprint, so this is purely for OS stability.

### Example: 4 GB system

| Scenario | Available | Budget | Workers |
|----------|-----------|--------|---------|
| Idle OS | 2,500 MB | 2,000 MB | min(4, 5) = **4** |
| Moderate pressure | 1,500 MB | 1,000 MB | min(4, 2) = **2** |
| High pressure | 800 MB | 300 MB | max(1, 0) = **1** |
| Critical (pauses) | 400 MB | -100 MB | wait → proceed with **1** |

---

## Files to Create / Modify

| File | Action | Notes |
|------|--------|-------|
| `pyproject.toml` | Modify | Add `psutil>=5.9.0,<7.0` to `dependencies` |
| `backend/pipeline/memory_utils.py` | Create | `get_available_memory_mb()`, `compute_safe_concurrency()`, `wait_for_memory()` |
| `backend/pipeline/pipeline_config.py` | Modify | 4 new fields with defaults |
| `backend/pipeline/ingestion.py` | Modify | Integrate adaptive concurrency into batch loop in `_run_group`; pass `active_jobs` from `process_import_job` |
| `backend/tests/unit/test_memory_utils.py` | Create | Unit tests with mocked psutil |

---

## `memory_utils.py` API

```python
def get_available_memory_mb() -> int | None:
    """Return available system RAM in MB, or None if psutil unavailable."""

def compute_safe_concurrency(
    configured_max: int,
    active_jobs: int,
    available_mb: int,
    memory_per_worker_mb: int,
    safety_reserve_mb: int,
) -> int:
    """Return safe worker count given current available memory.

    Always returns at least 1.
    """

def wait_for_memory(
    required_mb: int,
    timeout_s: float,
    poll_s: float,
    logger: logging.Logger,
    context: str = "",
) -> bool:
    """Poll until required_mb is available or timeout expires.

    Returns True if memory became available, False if timed out.
    """
```

---

## Integration in `_run_group`

```python
concurrency = pipeline_config.max_concurrent_prepare  # initial/fallback
last_logged_concurrency = concurrency

for batch_start in range(0, len(valid_files), batch_size):
    batch = valid_files[batch_start : batch_start + batch_size]

    # --- Adaptive memory check ---
    available_mb = get_available_memory_mb()
    if available_mb is not None:
        required_mb = (
            pipeline_config.memory_safety_reserve_mb
            + pipeline_config.memory_per_prepare_worker_mb
        )
        if available_mb < required_mb:
            logger.warning(
                "[%s] Low memory (%.0f MB available, need %.0f MB for 1 worker) — "
                "waiting up to %ds",
                group_name, available_mb, required_mb,
                pipeline_config.memory_wait_timeout_s,
            )
            wait_for_memory(
                required_mb=required_mb,
                timeout_s=pipeline_config.memory_wait_timeout_s,
                poll_s=pipeline_config.memory_wait_poll_s,
                logger=logger,
                context=f"[{group_name}]",
            )
            available_mb = get_available_memory_mb() or available_mb

        concurrency = compute_safe_concurrency(
            configured_max=pipeline_config.max_concurrent_prepare,
            active_jobs=active_jobs,
            available_mb=available_mb,
            memory_per_worker_mb=pipeline_config.memory_per_prepare_worker_mb,
            safety_reserve_mb=pipeline_config.memory_safety_reserve_mb,
        )
        if concurrency != last_logged_concurrency:
            logger.info(
                "[%s] Prepare concurrency: %d → %d (%.0f MB available, %d active jobs)",
                group_name, last_logged_concurrency, concurrency,
                available_mb, active_jobs,
            )
            last_logged_concurrency = concurrency

    with ThreadPoolExecutor(max_workers=concurrency) as prep_pool:
        ...
```

---

## Passing `active_jobs` into `_run_group`

`process_import_job` already iterates over groups sequentially. Before the group loop, query the JobRunner for the count of running import-type jobs:

```python
# In process_import_job, before group loop:
active_jobs = max(1, _count_active_import_jobs())

# Then:
_run_group(..., active_jobs=active_jobs)
```

`_count_active_import_jobs()` counts `JobRunner` records with status `"running"` and name containing `"Import"`.

The count is computed once at job start (not per-batch) since job turnover is slow relative to batch duration.

---

## Fallback Behaviour

If `psutil` is not importable (e.g., older Electron bundle), `get_available_memory_mb()` returns `None` and the pipeline falls back to the static `pipeline_config.max_concurrent_prepare` value. No crash, no functional regression.

---

## Testing

`test_memory_utils.py` covers:

- `compute_safe_concurrency` at various available memory levels (abundant, moderate, critically low)
- `compute_safe_concurrency` with multiple active jobs
- `compute_safe_concurrency` always returns ≥ 1
- `wait_for_memory` returns True when memory becomes available within timeout
- `wait_for_memory` returns False and logs on timeout
- `get_available_memory_mb` returns None gracefully when psutil unavailable

All psutil calls are mocked — no real memory state dependency in tests.
