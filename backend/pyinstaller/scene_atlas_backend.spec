# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the Scene Atlas backend sidecar.
#
# Build with:
#   uv run python scripts/build/build_sidecar.py
# or directly:
#   uv run pyinstaller backend/pyinstaller/scene_atlas_backend.spec
#
# Output: backend/pyinstaller/dist/scene-atlas-backend/
# The build_sidecar.py script copies this to the Electron extraResources path.
#
# ONNX models are NOT bundled — they are downloaded from HuggingFace at
# runtime by model_download_service.  The sidecar only needs huggingface_hub
# for downloading and onnxruntime for inference.

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

# Project root (2 levels up from this spec file: backend/pyinstaller -> backend -> root)
project_root = Path(SPECPATH).parent.parent
sys.path.insert(0, str(project_root))

# ── tokenizers: lightweight Rust binary (used for CLIP text tokenization)
tokenizers_datas, tokenizers_binaries, tokenizers_hiddenimports = collect_all('tokenizers')

# ── lancedb: Rust-backed vector database with a large native extension (_lancedb.abi3.so/.pyd)
lancedb_datas, lancedb_binaries, lancedb_hiddenimports = collect_all('lancedb')

# ── onnxruntime: CLIP inference engine (replaces torch)
ort_datas    = collect_data_files('onnxruntime')
ort_binaries = collect_dynamic_libs('onnxruntime')

import os as _os
import platform as _platform
import re as _re

a = Analysis(
    [str(project_root / 'backend' / 'pyinstaller' / 'entry.py')],
    pathex=[str(project_root)],
    binaries=tokenizers_binaries + ort_binaries + lancedb_binaries,
    datas=tokenizers_datas + ort_datas + lancedb_datas + [
        # Alembic migrations: alembic.ini + backend/alembic/ bundled into _MEIPASS root
        # database.py detects sys.frozen and reads from sys._MEIPASS instead of __file__
        (str(project_root / 'alembic.ini'),          '.'),
        (str(project_root / 'backend' / 'alembic'),  'backend/alembic'),
        # The built UI: Electron loads it from the sidecar (same origin as the API).
        (str(project_root / 'frontend' / 'dist'),    'frontend/dist'),
        # Data files read relative to their module (Path(__file__).parent): the tag
        # vocabulary (first-boot tag seeding) and the grid detection models.
        (str(project_root / 'backend' / 'app' / 'data' / 'tag_vocabulary.json'), 'backend/app/data'),
        (str(project_root / 'backend' / 'app' / 'data' / 'grid_models'),         'backend/app/data/grid_models'),
        (str(project_root / 'backend' / 'app' / 'data' / 'heads'),               'backend/app/data/heads'),
    ],
    hiddenimports=[
        # uvicorn internals
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # FastAPI / Starlette
        'fastapi',
        'starlette',
        'starlette.middleware',
        'starlette.middleware.cors',
        # SQLAlchemy dialects
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.dialects.sqlite.pysqlite',
        # Alembic
        'alembic',
        'alembic.config',
        # Pydantic
        'pydantic',
        'pydantic_settings',
        'pydantic_core',
        # Multipart / file uploads
        'multipart',
        'python_multipart',
        # aiofiles
        'aiofiles',
        'aiofiles.os',
        'aiofiles.threadpool',
        # LanceDB (disk-backed vector database)
        'lancedb',
        'pyarrow',
        # OpenCV (headless)
        'cv2',
        # scikit-learn
        'sklearn',
        'sklearn.utils._cython_blas',
        'sklearn.neighbors._partition_nodes',
        'sklearn.tree._utils',
        # scipy (full package collected — sklearn has transitive deps throughout)
        'scipy',
        'scipy.special._ufuncs_cxx',
        'scipy.linalg.cython_blas',
        'scipy.linalg.cython_lapack',
        # ONNX Runtime (CLIP inference)
        'onnxruntime',
        'onnxruntime.capi',
        # Tokenizers (CLIP text tokenization — HuggingFace fast tokenizer)
        'tokenizers',
        # SentencePiece (SigLIP2 text tokenization)
        'sentencepiece',
        # HuggingFace Hub (model downloads at runtime — lazy imports in model_download_service)
        'huggingface_hub',
        'huggingface_hub.utils',
        # Misc
        'numpy',
        'PIL',
        'PIL.Image',
        'yaml',
    ] + tokenizers_hiddenimports + lancedb_hiddenimports,
    excludes=[
        # GUI toolkits — not needed server-side
        'tkinter',
        '_tkinter',
        'wx',
        'PyQt5',
        'PyQt6',
        # Dev/test tools
        'pytest',
        'pytest_asyncio',
        'ruff',
        'ipywidgets',
        'matplotlib',
        'notebook',
        'jupyter',
        'ipython',
        'jedi',           # IDE code completion — not needed at runtime
        # torch/transformers — replaced by onnxruntime (exclude in case of transitive deps)
        'torch',
        'transformers',
        'triton',         # GPU JIT compiler
        # Unused database drivers (project uses SQLite, not PostgreSQL)
        'asyncpg',
        # gRPC — no longer needed (was required by qdrant_client)
        'grpc',
        'grpcio',
        # HuggingFace download accelerator — not needed in frozen sidecar
        'hf_xet',
        # Prefect (removed — exclude in case of transitive dependency)
        'prefect',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

# ── Post-analysis cleanup ─────────────────────────────────────────────────────
# Remove directories and files that hooks collect but are never needed at runtime.

# On Windows, strip=True can corrupt DLLs if MSYS2 strip.exe is on PATH.
# PyInstaller's strip only affects ELF/Mach-O binaries on Linux/macOS.
_strip_binaries = _platform.system() != 'Windows'

# CUDA shared libraries — always stripped from electron builds.
# onnxruntime-gpu may be co-installed in the dev venv; collect_dynamic_libs
# will scoop up ~1.8 GB of CUDA .so/.dll files we don't want.
_CUDA_LIB_RE = _re.compile(
    r'(libcu(blas|fft|rand|dnn|solver|sparse|pti|dart)'
    r'|libnv(rtc|JitLink)'
    r'|libonnxruntime_providers_cuda)'
)

# .dist-info directories are package metadata — safe to strip at runtime
# EXCEPT for packages that read their own metadata at import time:
#  - onnxruntime: DirectML uses entry_points.txt for plugin registration
#  - lancedb: reads its version via importlib.metadata at import
_DIST_INFO_RE = _re.compile(r'\.dist-info/')

def _keep_entry(entry):
    name = entry[0].replace('\\', '/')
    if _DIST_INFO_RE.search(name):
        if 'onnxruntime' in name:
            pass  # keep — DirectML needs entry_points.txt
        elif 'lancedb' in name:
            pass  # keep — lancedb reads its own version via importlib.metadata at import
        else:
            return False
    if _CUDA_LIB_RE.search(name):
        return False
    return True

a.binaries = TOC([e for e in a.binaries if _keep_entry(e)])
a.datas    = TOC([e for e in a.datas    if _keep_entry(e)])
# ─────────────────────────────────────────────────────────────────────────────

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='scene-atlas-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=_strip_binaries,  # Strip debug symbols (disabled on Windows to protect DLLs)
    upx=True,           # UPX-compress binaries
    console=True,       # Must be True: stdout is how we signal SCENE_ATLAS_READY
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Note: a.zipfiles was removed in PyInstaller 6 — do not pass it to COLLECT
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=_strip_binaries,  # Strip debug symbols (disabled on Windows to protect DLLs)
    upx=True,
    upx_exclude=[
        # OpenCV — monolithic .so with complex symbol resolution
        'cv2.abi3.so',
        # DirectML DLLs must not be UPX-compressed — they are loaded by the
        # onnxruntime DML execution provider at runtime via LoadLibrary.
        # Harmless to list on non-Windows (files simply won't exist).
        'DirectML.dll',
        'onnxruntime_providers_dml.dll',
    ],
    name='scene-atlas-backend',
)
