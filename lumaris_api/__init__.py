"""lumaris_api package marker + flat-layout import shim.

This project uses a FLAT module layout: the modules in this directory import each other by
BARE name (``import db``, ``import observability``, ``from pricing import ...``) and the test
suite runs each file with the working directory set to this folder. That works in-tree.

It breaks, however, for the canonical repo-root launch::

    python -m uvicorn lumaris_api.main:app --host 0.0.0.0 --port 8000

because ``-m`` puts the REPO ROOT first on ``sys.path``, where the sibling top-level
``observability/`` directory (Grafana / Prometheus / OTel configs) shadows
``lumaris_api/observability.py`` — so ``import observability`` inside main.py imports the wrong
thing and the app fails to start. Operators worked around this with ``cd lumaris_api`` first,
which is exactly the working-directory trick we want to eliminate.

Importing this package (which always happens before ``lumaris_api.main`` is imported) prepends
THIS directory to ``sys.path`` so every bare sibling import resolves to lumaris_api's own
modules first, regardless of the process CWD. The insert is idempotent and keyed on
``__file__`` — not the CWD — so ``python -m uvicorn lumaris_api.main:app`` now works from the
repo root without shadowing, while the flat cwd-based test harness is completely unaffected
(running a module as a script never triggers this ``__init__``).
"""
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
# Force to the FRONT even if already present at a later position.
try:
    _sys.path.remove(_HERE)
except ValueError:
    pass
_sys.path.insert(0, _HERE)
