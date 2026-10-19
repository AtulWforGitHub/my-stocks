"""Multibagger Intelligence System."""
try:
    import numpy, pandas, yaml  # noqa: F401
except ImportError as _e:  # pragma: no cover
    raise SystemExit(f"Missing Python package '{_e.name}'. From the mis-tool folder run:\n"
                     "  .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt")
