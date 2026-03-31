from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
BACKEND_SRC_DIR = BACKEND_DIR / "src"
VENV_PYTHON = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run burph5 as a single-port app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def ensure_backend_python() -> None:
    current_python = Path(sys.executable).resolve()
    if current_python == VENV_PYTHON.resolve():
        return
    if not VENV_PYTHON.exists():
        raise SystemExit(f"Backend virtualenv not found: {VENV_PYTHON}")

    subprocess.run([str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]], check=True)
    raise SystemExit(0)


def main() -> None:
    ensure_backend_python()

    sys.path.insert(0, str(BACKEND_SRC_DIR))

    import uvicorn

    from burph5.main import create_app

    args = parse_args()
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
