# Code Quality Baseline (pre-release)

Measured 2026-10-17 against `main` @ `d9dcf7f`, on branch `chore/code-quality-baseline`.
This is step 1 of the pre-release quality pass: **report only, no code changed**. Later
steps (cleanup, per-area review, gates) are scoped at the bottom.

## Summary

| Area | Result | Verdict |
|------|--------|---------|
| Existing gates (ruff check/format, ESLint, Prettier, tsc) | All pass | OK |
| Backend tests | 994 passed, 1 skipped; **88% line coverage** | Good |
| Frontend tests | 238 passed; **35% line coverage** (28% branches) | Weak |
| Copy-paste duplication (jscpd) | 0.33% — 11 clones, 127 lines | Low |
| Comment ratio (comments+docstrings / code) | 0.16 overall; 18 files ≥ 0.5 | Moderate, noisy in places |
| Dead code | ~20 real items (backend + frontend), 1 unused dep, 1 unused devDep | Small cleanup |
| pyright (`standard`) | **494 errors**, not enforced anywhere | Biggest structural gap |
| Extended ruff rules | 147 hits, mostly style; a few real | Small cleanup |

Overall: the code is in better shape than "LLM-written" usually implies. Textual
duplication is negligible and history/changelog-style comments are rare. The real gaps
are **type safety** (SQLAlchemy models), **frontend test coverage**, a handful of
**oversized functions/components**, and **comment noise** (banners, boilerplate docstrings).

## Local hooks were not running

Found while setting this up (fixed locally; no commit needed):

- `core.hooksPath` in `.git/config` was a mangled Windows UNC path
  (`…/\\wsl.localhost\ubuntu-22.04\…\.husky`), so **no git hooks ran from WSL/Linux**.
- `git lfs install` had overwritten `.husky/pre-push` and deleted `.husky/pre-commit`.

Fix applied: restored both hooks from git and re-ran `npx husky` from Linux, which sets the
relative `core.hooksPath=.husky/_`. That path works from Windows and WSL alike. The committed
`pre-push` already calls `git lfs pre-push`, so LFS is still covered. **Never run
`git lfs install` in this repo**; if LFS hooks go missing, re-run `npx husky` instead.

Because the hooks were off, CI was the only gate. The gates all pass today, so nothing slipped.

## Duplication

`jscpd` (min 8 lines / 70 tokens, tests excluded): 11 clones. All are local,
same-file or sibling-file repetition — no cross-layer copy-paste.

| Lines | Location | Note |
|------:|----------|------|
| 15+14+13+11 | `frontend/src/components/GridFilterIcons.tsx` (4 clones) | Repeated SVG scaffolding; extract a base icon component |
| 15, 13 | `backend/app/api/search.py` 203↔391, 163↔460 | Shared filter/query-building between the two search endpoints |
| 14 | `backend/app/api/export.py:100` ↔ `backend/pipeline/export_library.py:113` | Export logic in API and pipeline layers |
| 12 | `useEditGroupLoad.ts:49` ↔ `useEditGroupOperations.ts:185` | Shared group-load mapping |
| 11 | `backend/app/api/groups.py` 314↔383 | `move_images` / `merge_group` share a body |
| 10, 10 | `frontend/src/hooks/useFileEditing.ts` (2 clones) | Repeated update handlers |

Semantic duplication (same logic, different text) is not visible to jscpd; that is a step 3
review concern. Of the earlier code-review backlog (items #1–5), only the pipeline DB session
helper rollout remains; it is tracked in [status-and-roadmap.md](status-and-roadmap.md#backlog).

## Comments

Ranked list: `uv run python scripts/quality/comment_density.py`. Top files by ratio are
small docstring-heavy modules (`image_store.py` 1.34, `error_classifier.py` 1.17,
`validation.py` 0.88, `image_hashes.py` 0.80).

Pattern counts (non-test source):

| Pattern | Count | Action |
|---------|------:|--------|
| Banner/divider lines (`# ----`, `// ====`) | 177 | Remove most; a module-level section split rarely needs a 3-line banner |
| Google-style `Args:`/`Returns:` blocks | 41 | Remove where they restate the signature (e.g. `ImageStore.put_bytes`) |
| Section-label comments (`# Relationships`, `// Image viewer`) | many | Remove when the code below is self-evident |
| Step narration (`# Step 1:`) | 12 | Remove or replace with function extraction |
| Changelog-style ("previously…", "no longer…") | ~2 real | Reduce to the *why*, e.g. `database.py:288` engine-cache comment |
| TODO/FIXME/HACK | 0 | — |
| `noqa` / `type: ignore` / `eslint-disable` | 28 | Review each for a still-valid reason |

### Comment rubric (applies to step 3 review)

Delete:
- Comments that restate the code or the name (`# Check if migration is needed`).
- Docstrings on private/trivial helpers that only repeat the signature; `Args:`/`Returns:`
  sections that add nothing beyond the type hints.
- Narration (`Step 1:`), section labels over obvious code, decorative banners.
- History ("previously X, now Y", "fixed bug where…") — that belongs in git.
- Commented-out code.

Keep (and write):
- **Why**: non-obvious constraints, invariants, ordering requirements.
- Workarounds, with the reason and the condition for removing them.
- Platform quirks (Windows/macOS/PyInstaller/Electron).
- Pointers to `design/` docs and ADRs.
- Docstrings on public service/API functions where behaviour isn't obvious from the name.

Good examples already in the code: `database.py:63` (no cascade to ImportJob — explains a
deliberate absence) and `database.py:428–443` (PyInstaller `_MEIPASS` resolution).

## Dead code

Verified by hand; vulture and knip false positives (FastAPI routes, Pydantic fields,
slowapi's required `request` arg, `hash.worker.ts` loaded via `new URL()`) are excluded.

**Backend** (vulture, 60% confidence, then checked):
- `models/database.py:338` `_migrate_images_content_hash` — never called; superseded by Alembic.
- `services/image_store.py` `put_bytes`, `generate_key`
- `services/lancedb_service.py` `add_image_embedding`, `get_embedding`, `get_embeddings`
- `services/job_runner.py` `run_sync`, `is_shutting_down`
- `services/ingest_state.py` `target_of`; `services/validation.py` `is_path_within`;
  `services/model_registry.py` `get_gpu_provider_label`; `services/image_parser.py` `_strip_word_prefix`;
  `pipeline/image_hashes.py` `hamming_distance`; `pipeline/ingest_worker.py` `drain`;
  `config.py` `all_supported_formats`; `services/clip_service.py` `active_providers`;
  `services/memory_budget.py` `in_use`; `models/database.py` `group_image_count`
- Check each for test-only use before deleting: if only tests use it, delete both
  unless the test exercises a real contract.

**Frontend** (knip):
- Unused files: `components/ui/{badge,card,sheet,error-alert}.tsx`, `hooks/useAppMode.ts`.
- Unused deps: `@dnd-kit/utilities`, `@radix-ui/react-dialog`; devDep `msw`.
- Unused exports: `getErrorMessage.ts` `isConflictError`, `TagColorContext.tsx`
  `useCategoryColorMap`/`buildColorLookup`, `constants.ts` `CANVAS_DOT_SIZE`. Also
  `lib/import/hasher.ts` `WorkerHasher`/`noopHasher`/`MAX_CLIENT_HASH_BYTES`, but these are
  used internally via `createHasher()`, so only the `export` keyword is surplus.
- `ui/dropdown-menu.tsx`, `ui/button.tsx`, `ui/input.tsx` unused exports are shadcn
  boilerplate; trim with the unused `ui/` files.
- 24 unused exported types — mostly harmless `Props`/`Return` exports; ignore.

## Types (pyright)

494 errors in `standard` mode. **364 (~74%)** come from `backend/app/models/database.py`
using legacy `Column(...)` declarations (100 columns, 0 `Mapped[]`), so pyright sees
`Column[str]` where code uses `str`. Hotspots: `pipeline/ingest_queue.py` (124),
`api/imports.py` (68), `api/groups.py` (41).

Migrating the models to SQLAlchemy 2.0 `Mapped[...]` / `mapped_column()` is mechanical,
schema-neutral (no migration needed), and should drop the count to ~130. The remainder
can then be fixed and pyright added to CI. Without this, type hints across the pipeline
are largely decorative.

## Complexity and size

Functions over 50 statements (ruff `PLR0915`), excluding dev scripts:

| Function | Statements |
|----------|-----------:|
| `api/search.py:391` (main search endpoint) | 134 |
| `main.py:41` (lifespan) | 111 |
| `services/image_parser.py:667` | 92 |
| `api/search.py:203` | 69 |
| `pipeline/write_new_embeddings.py:22` | 67 |
| `pipeline/export_library.py:42` | 59 |
| `pipeline/ingest_archive.py:82`, `api/imports.py:517`, `ingest_process.py:409`, `clip_service.py:241` | 52–55 |

Largest frontend files (~1000 lines each): `FilterMenuContent.tsx`, `TagManagementDialog.tsx`,
`EditGroupDialog.tsx`, `ImageViewer.tsx`, `lib/import/ImportManager.ts`.

`search.py` stands out: the largest function, two internal clones, 20 pyright errors.
It is the core feature and the best single refactor target.

## Test coverage gaps

Backend modules ≥100 statements below 85%:

| Module | Coverage |
|--------|---------:|
| `pipeline/backfill_grid_detection.py` | 26% |
| `services/lancedb_service.py` | 67% |
| `services/clip_service.py` | 68% |
| `main.py` | 71% |
| `api/models.py` | 73% |
| `pipeline/maintenance.py` | 80% |
| `pipeline/ingest_worker.py` | 82% |
| `api/search.py` | 84% |

Frontend at 35% is the larger risk: refactoring the 1000-line components (step 3) without
tests is unsafe. Add characterisation tests before touching them.

## Other observations

- Extended ruff: 19× `TRY400` (`logger.error` inside `except` drops the traceback; use
  `logger.exception`) — worth fixing for supportability. 21× `PLW0603` (`global`) are
  mostly service singletons; leave unless reviewing that module anyway.
- `react-hooks/set-state-in-effect` is disabled globally (`frontend/eslint.config.js`).
  Not release-blocking.
- `uv sync` with no extras gives an environment that can't import the app (`onnxruntime`
  lives in the `cpu`/`gpu` extras). Developers must use `uv sync --extra dev --extra cpu`
  as in CONTRIBUTING.md.

## Reproducing

```bash
uv sync --extra dev --extra cpu
uv run python -m pytest backend/tests --cov=backend/app --cov=backend/pipeline
(cd frontend && npx vitest run --coverage)
npx jscpd@4.0.5 backend/app backend/pipeline scripts frontend/src electron \
  --ignore "**/node_modules/**,**/dist/**,**/*.test.*,**/__tests__/**,**/tests/**" \
  --min-lines 8 --min-tokens 70
(cd frontend && npx knip@6.42.0)
uvx vulture backend/app backend/pipeline scripts --min-confidence 60
uvx pyright@1.1.414 --pythonpath .venv/bin/python
uv run ruff check backend/ scripts/ --exclude backend/tests \
  --select ERA,SIM,RET,PIE,ARG,RUF,PLR,PLW,PERF,TRY \
  --ignore PLR2004,PLR0913,TRY003,RUF001,RUF002,RUF003 --statistics
uv run python scripts/quality/comment_density.py
```

## Progress

- **Step 2 (mechanical cleanup) — done** on `chore/code-quality-baseline`:
  - Removed backend dead code (legacy `_migrate_images_content_hash`, `generate_clip_embedding`,
    `ImageStore.generate_key`, `JobRunner.run_sync`, `is_shutting_down`, `is_path_within`,
    `_strip_word_prefix`, `all_supported_formats`, `ClipService.active_providers`).
    Kept `put_bytes`, `target_of`, `hamming_distance`, `in_use` and `group_image_count`:
    they are small public APIs, used by serialisation or tests that check real contracts.
  - Removed log-and-reraise wrappers (callers already log); `logger.exception` where
    errors are swallowed. `lancedb_service.py` was left to the search/perf branch.
  - Frontend: removed 5 unused files, 3 unused deps, unused exports.
  - Deduplicated export naming (`naming.unique_export_path` / `export_metadata`), grid
    filter icons, bulk-edit helpers, group-edit payload mapping. jscpd: 11 → 3 clones;
    the remaining 3 (`search.py`, `groups.py`) belong to the search/perf branch.
  - Fixed a test-isolation bug: root-endpoint tests failed whenever `frontend/dist`
    existed locally.
- **Step 4 (types) — done except the modules on the search/perf branch**, on
  `refactor/sqlalchemy-mapped` (stacked on step 2):
  - Models migrated to `Mapped[]` / `mapped_column()`. Verified schema-neutral by diffing
    the generated DDL, column options and relationships before and after (identical).
  - Declared 8 indexes that migrations create but the models omitted
    (`ix_images_{variant_group_id,gridded,grid_type,image_type,media_type}`,
    `ix_tags_image_id`, `ix_tags_category_value`, `ix_colors_image_id`). Remaining
    model-vs-migration drift is benign: FTS5 shadow tables, an FK on
    `images.import_job_id` SQLite can't add without a table rebuild, and nullability /
    uniqueness nits on `app_settings.updated_at` and `tag_categories.name`.
  - pyright scoped to production code (`backend/tests`, `backend/scripts` excluded).
    494 → 66 errors, all in `api/{imports,search,groups}.py`, `ingest_queue.py`,
    `lancedb_service.py` (mostly Optional `db`/`_table` access) and
    `model_download_service.py`. Fix after the search/perf branch merges, then gate.
  - **Bug found and fixed:** with lancedb 0.30, `name in db.list_tables()` is always
    False (`ListTablesResponse`). Changing the embedding vector size crashed startup
    with a schema mismatch, and `GET /models/{name}/embeddings` always reported 0
    vectors. Fixed via `LanceDBService.table_exists()`, with regression tests.
- **Search refactor + N+1 fixes** — merged from `perf/search-and-queries`
  (`backend/app/services/search_service.py`).
- **Stale docs** (`design/ingestion.md` describing the pre-ADR-018 pipeline,
  `design/testing.md` fixtures) — rewritten in the pre-release docs pass.

## Completed steps

All five steps landed on one branch (combined PR):

2. **Mechanical cleanup**: dead code, unused deps, duplicate logging, jscpd clones.
3. **Per-area review**: frontend components, hooks/lib, Electron and all design docs were
   reviewed against the rubric; findings applied (see the commit history). The larger
   frontend extractions deferred here (EditGroupDialog/ImageViewer subcomponents,
   `useSceneFilters`, unified scene/file filtering, shared `TagChip`/`PanelTitle`) were done
   later, after characterisation tests; see [frontend.md](frontend.md).
4. **Types**: `Mapped[]` models; pyright at 0 errors.
5. **Gates**: pre-push and the CI `quality` job run pyright, knip (`frontend/knip.json`) and
   jscpd (`.jscpd.json`, 1% threshold). Ruff now also enforces `SIM`, `RET`, `PIE`, `RUF100`
   and `TRY400`. `ERA` (commented-out code) was left out: in this codebase it only flagged
   section comments and data-layout comments.

The query-scaling items (#6–10, N+1 queries) were resolved or made obsolete on
`perf/search-and-queries`; query counts are pinned by `integration/test_query_counts.py`.

## Codacy configuration

Tuned 2026-10-19 with the Codacy Analysis CLI, then imported to Cloud (Cloud open issues 1079 → 315).
Tool and pattern selection lives in Codacy; `.codacy.yml` only scopes paths. The principle: Codacy adds
what the local gates (ruff, ESLint, Prettier, pyright) don't already enforce, and never contradicts them.

- **Enabled:** ESLint9 (Codacy-managed patterns), Opengrep/Semgrep, Trivy, Bandit (B615 only), Lizard,
  Stylelint, markdownlint, Hadolint, Checkov, Agentlinter, Jackson, Ruff (uses `pyproject.toml`).
- **ESLint9, not ESLint8:** ESLint8 is EOL. In the managed set, formatting rules are off (Prettier owns
  them), as are React rules that are wrong for TS / the automatic JSX runtime (`react-in-jsx-scope`,
  `prop-types`) and the react-hooks rules disabled in `frontend/eslint.config.js`. Also off:
  `no-confusing-void-expression`, `no-non-null-assertion`, base `no-unused-vars` (flags TS
  signature params), and `no-redundant-type-constituents` (Codacy can't resolve `@/`, so types become
  `any`). Kept: security, security-node, jsx-a11y, React correctness, type-aware promise rules.
- **Security dedup:** prototype pollution, non-literal fs paths and XSS are covered by Semgrep rules,
  so ESLint's `detect-object-injection` (every typed index access), `detect-non-literal-fs-filename`
  and `xss/no-mixed-html` are off. Bandit is limited to B615 because Ruff's `S` rules cover the rest.
- **Semgrep:** the old Cloud set was mostly Apex/C/C#/Java rules; now stack-targeted plus gitleaks
  secrets. `package-dependencies-check` is off: lockfiles pin versions and Trivy scans them.
- **Lizard:** `nloc-medium` 100 (React components are long), `parameter-count-medium` 12 (Lizard
  counts destructured props); `ccn-minor` off, `ccn-medium` 15 stays.
- **Rejected:** PyLint (Python runtime older than 3.11; duplicates Ruff + pyright), Prospector
  (crashes), PMD7 (can't parse ES modules), spectral (no OpenAPI files).

Local analysis: the Codacy IDE extension resyncs `.codacy/codacy.config.json` from Cloud. Trivy's
filesystem walk enters gitignored `.claude/worktrees/` and times out locally, which doesn't happen on Cloud.
