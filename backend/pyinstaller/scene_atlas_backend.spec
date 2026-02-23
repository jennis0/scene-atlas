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
from PyInstaller.utils.hooks import collect_all

# Project root (2 levels up from this spec file: backend/pyinstaller -> backend -> root)
project_root = Path(SPECPATH).parent.parent
sys.path.insert(0, str(project_root))

# collect_all must be called BEFORE Analysis and results passed as constructor
# args — appending to a.datas/a.binaries after the fact mixes incompatible
# tuple formats (2-tuple input vs 3-tuple internal) and breaks normalize_toc.
torch_datas,        torch_binaries,        torch_hiddenimports        = collect_all('torch')
transformers_datas, transformers_binaries, transformers_hiddenimports = collect_all('transformers')
tokenizers_datas,   tokenizers_binaries,   tokenizers_hiddenimports   = collect_all('tokenizers')

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
        # OpenCV
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
        'transformers',
        'transformers.models.clip',
        'tokenizers',
        # Torch (CPU)
        'torch',
        'torch.nn',
        'torch.nn.functional',
        # Misc
        'numpy',
        'PIL',
        'PIL.Image',
        'yaml',
    ] + torch_hiddenimports + transformers_hiddenimports + tokenizers_hiddenimports,
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
        # CUDA — ship CPU-only torch
        'torch.cuda',
        # Prefect (removed — exclude in case of transitive dependency)
        'prefect',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='scene-atlas-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
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
    strip=False,
    upx=False,
    upx_exclude=[],
    name='scene-atlas-backend',
)
