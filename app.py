from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
BACKEND_SRC_DIR = BACKEND_DIR / "src"
INSTALL_HINT = (
    "Missing backend dependencies.\n"
    f"Run:\n  cd {ROOT_DIR}\n  python -m pip install -r requirements.txt"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run burph5 as a single-port app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def ensure_backend_source_path() -> None:
    if not BACKEND_SRC_DIR.exists():
        raise SystemExit(f"Backend source directory not found: {BACKEND_SRC_DIR}")

    backend_src = str(BACKEND_SRC_DIR)
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)


def main() -> None:
    ensure_backend_source_path()
    try:
        import uvicorn
        from burph5.main import create_app
    except ModuleNotFoundError as exc:
        raise SystemExit(f"{INSTALL_HINT}\n\nImport error: {exc}") from exc

    args = parse_args()
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
