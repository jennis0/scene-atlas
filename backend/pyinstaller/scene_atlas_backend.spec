# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the Scene Atlas backend sidecar.
#
# Build with:
#   uv run python scripts/build_sidecar.py
# or directly:
#   uv run pyinstaller backend/pyinstaller/scene_atlas_backend.spec
#
# Output: backend/pyinstaller/dist/scene-atlas-backend/
# The build_sidecar.py script copies this to the Electron extraResources path.

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# Project root (2 levels up from this spec file: backend/pyinstaller -> backend -> root)
project_root = Path(SPECPATH).parent.parent
sys.path.insert(0, str(project_root))

# -- torch: collect binaries only (no Python .pyc — they come via hiddenimports)
torch_datas    = collect_data_files('torch', includes=['**/*.so', '**/*.pth'])
torch_binaries = collect_dynamic_libs('torch')

# -- transformers: targeted collection for CLIP only (avoids bundling model configs
#    for hundreds of model types that collect_all would pull in)
transformers_datas    = collect_data_files('transformers', includes=['**/*.json', '**/*.txt'])
transformers_binaries = collect_dynamic_libs('transformers')
transformers_hiddenimports = [
    'transformers',
    'transformers.models.clip',
    'transformers.models.clip.modeling_clip',
    'transformers.models.clip.processing_clip',
    'transformers.models.clip.tokenization_clip',
    'transformers.models.clip.feature_extraction_clip',
    'transformers.image_processing_utils',
    'transformers.tokenization_utils',
    'transformers.tokenization_utils_base',
    'transformers.tokenization_utils_fast',
]

# -- tokenizers: lightweight Rust binary
from PyInstaller.utils.hooks import collect_all as _collect_all
tokenizers_datas, tokenizers_binaries, tokenizers_hiddenimports = _collect_all('tokenizers')

a = Analysis(
    [str(project_root / 'backend' / 'pyinstaller' / 'entry.py')],
    pathex=[str(project_root)],
    binaries=torch_binaries + transformers_binaries + tokenizers_binaries,
    datas=torch_datas + transformers_datas + tokenizers_datas + [
        # Alembic migrations: alembic.ini + backend/alembic/ bundled into _MEIPASS root
        # database.py detects sys.frozen and reads from sys._MEIPASS instead of __file__
        (str(project_root / 'alembic.ini'),          '.'),
        (str(project_root / 'backend' / 'alembic'),  'backend/alembic'),
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
        # Qdrant client (embedded mode)
        'qdrant_client',
        'qdrant_client.local',
        'qdrant_client.local.local_collection',
        # OpenCV (headless)
        'cv2',
        # scikit-learn
        'sklearn',
        'sklearn.utils._cython_blas',
        'sklearn.neighbors._partition_nodes',
        'sklearn.tree._utils',
        # scipy
        'scipy',
        'scipy.special._ufuncs_cxx',
        'scipy.linalg.cython_blas',
        'scipy.linalg.cython_lapack',
        # Transformers / HuggingFace
        'tokenizers',
        # Torch (CPU-only — torch installed via pytorch-cpu index)
        'torch',
        'torch.nn',
        'torch.nn.functional',
        # Misc
        'numpy',
        'PIL',
        'PIL.Image',
        'yaml',
    ] + transformers_hiddenimports + tokenizers_hiddenimports,
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
        # GPU / CUDA — CPU-only torch is used; these should not be present,
        # but listed defensively in case of transitive imports
        'torch.cuda',
        'torch.backends.cuda',
        'torch.backends.cudnn',
        'torch.distributed',
        'torch.ao',
        'torch.profiler',
        'torch.testing',
        'triton',         # GPU JIT compiler
        # Unused database drivers (project uses SQLite, not PostgreSQL)
        'asyncpg',
        # Qdrant remote mode — project uses local embedded mode only
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
import re as _re

# Prefixes to strip from binaries and datas.
_JUNK_PREFIXES = (
    # torch: C++ unit tests (~58 MB), standalone tools (~36 MB), cmake/share files
    'torch/test/',
    'torch/bin/',
    'torch/share/',
    # torch: test shared libraries that sneak into torch/lib/
    'torch/lib/libtorchbind_test',
    'torch/lib/libjitbackend_test',
    'torch/lib/libaoti_custom_ops',
    'torch/lib/libbackend_with_compiler',
    # transformers: 370+ model directories we don't use — only CLIP is needed
    'transformers/models/',
    # scipy: unused submodules (only scipy.signal + scipy.fft are used)
    'scipy/stats/',
    'scipy/optimize/',
    'scipy/interpolate/',
    'scipy/sparse/',
    'scipy/integrate/',
    'scipy/io/',
    'scipy/spatial/',
)

# Transformers model dirs to KEEP (everything else under transformers/models/ is removed)
_TRANSFORMERS_KEEP = {'clip', 'auto', '__init__'}

# .dist-info directories are package metadata — not needed at runtime
_DIST_INFO_RE = _re.compile(r'\.dist-info/')

def _keep_entry(entry):
    name = entry[0].replace('\\', '/')
    # Drop .dist-info metadata
    if _DIST_INFO_RE.search(name):
        return False
    # Check junk prefixes
    for prefix in _JUNK_PREFIXES:
        if name.startswith(prefix) or f'/{prefix}' in name:
            # Special case: allow transformers model dirs we actually need
            if 'transformers/models/' in prefix:
                parts = name.split('transformers/models/')
                if len(parts) > 1:
                    subdir = parts[1].split('/')[0]
                    if subdir in _TRANSFORMERS_KEEP:
                        return True
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
    strip=True,         # Strip debug symbols from binaries — safe on Linux, saves 20-40%
    upx=False,          # UPX causes issues with torch and opencv native libs
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
    strip=True,         # Strip debug symbols — matches EXE setting above
    upx=False,
    upx_exclude=[],
    name='scene-atlas-backend',
)
