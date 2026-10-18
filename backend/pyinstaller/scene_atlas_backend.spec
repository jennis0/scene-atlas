# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the Scene Atlas backend sidecar.
#
# Build with:
#   uv run python scripts/build/build_sidecar.py
# which runs PyInstaller from .venv-sidecar, a venv holding only the runtime
# dependencies. Don't run it from the dev venv: PyInstaller bundles whatever optional
# imports it can resolve, so the dev tools (IPython, transformers, onnx...) come too.
#
# Output: backend/pyinstaller/dist/scene-atlas-backend/, which electron-builder's
# extraResources bundles as resources/sidecar/.
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
        # scipy (grid detection: ndimage, signal)
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
    # Dev tools need no excludes: the build venv doesn't have them (see the header).
    # These are optional parts of runtime packages that their importers already treat
    # as missing-is-fine (try/except ImportError), checked against the import tables.
    excludes=[
        'tkinter',
        '_tkinter',
        # pyarrow: Arrow Flight RPC, Substrait plans and the cloud filesystems. LanceDB
        # uses none of them; pyarrow.fs imports each filesystem inside try/except.
        'pyarrow.flight',
        'pyarrow._flight',
        'pyarrow.substrait',
        'pyarrow._substrait',
        'pyarrow._s3fs',
        'pyarrow._gcsfs',
        'pyarrow._azurefs',
        'pyarrow._hdfs',
        # Pillow's AVIF codec (7 MB): AVIF isn't an import format, and the plugin
        # sets SUPPORTED = False without it.
        'PIL._avif',
        # Download accelerator: plain HTTP is enough for a one-off model download.
        'hf_xet',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

# ── Post-analysis cleanup ─────────────────────────────────────────────────────
# Remove directories and files that hooks collect but are never needed at runtime.

# Never strip: on Linux it breaks the patchelf-repaired libraries in manylinux wheels
# (numpy's OpenBLAS and libgfortran fail to load: "ELF load command address/offset not
# page-aligned"), on macOS it invalidates the wheels' signatures, and on Windows an
# MSYS2 strip.exe on PATH corrupts DLLs. It saved little; the installers compress.
_strip_binaries = False

# CUDA shared libraries — always stripped from electron builds.
# With --ort-extra gpu, collect_dynamic_libs would scoop up ~1.8 GB of CUDA
# .so/.dll files we don't want.
_CUDA_LIB_RE = _re.compile(
    r'(libcu(blas|fft|rand|dnn|solver|sparse|pti|dart)'
    r'|libnv(rtc|JitLink)'
    r'|libonnxruntime_providers_cuda)'
)

# pyarrow files nothing loads at runtime: the libraries of the modules excluded above
# (only those modules link them, per their import tables), and the C++ headers,
# Cython sources, import libraries and tests the wheel ships for building extensions.
_PYARROW_UNUSED_RE = _re.compile(
    r'^pyarrow/('
    r'(lib)?arrow_(python_)?(flight|substrait|s3)[^/]*\.(dll|so[.\d]*|dylib)'
    r'|(include|includes|src|tests)/.*'
    r'|[^/]*\.(lib|pxd|pyx|pxi|h)'
    r')$'
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
    if _CUDA_LIB_RE.search(name) or _PYARROW_UNUSED_RE.search(name):
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
    upx=False,
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
    # No UPX: it corrupted numpy's bundled OpenBLAS (ELF segments no longer page-aligned),
    # slows every start (each library is decompressed on load), and Windows antivirus
    # flags UPX-packed DLLs. The installers compress the payload anyway.
    upx=False,
    name='scene-atlas-backend',
)
