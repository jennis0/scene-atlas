#!/usr/bin/env python3
"""Legacy wrapper — delegates to export_model_onnx.py with CLIP defaults."""

import subprocess
import sys
from pathlib import Path

script = Path(__file__).parent / "export_model_onnx.py"
sys.exit(subprocess.call([sys.executable, str(script)] + sys.argv[1:]))
