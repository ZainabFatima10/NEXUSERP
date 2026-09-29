"""
Every ai-module service is a flat top-level module (no package/src layout —
`from taxonomy import ...`, `from database import get_db`, etc.), because
uvicorn is always launched with this directory as the cwd. pytest doesn't
get that cwd for free, so make this directory importable regardless of where
`pytest` is invoked from.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
