from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppSettings:
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    proxy_host: str = "127.0.0.1"
    proxy_port: int = 8899
    default_timeout_ms: int = 15000
    max_concurrency: int = 5
    backend_root: Path = Path(__file__).resolve().parents[2]

    @property
    def data_dir(self) -> Path:
        return self.backend_root / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "burph5.db"

    @property
    def certs_dir(self) -> Path:
        return self.data_dir / "certs"

    @property
    def captures_dir(self) -> Path:
        return self.data_dir / "captures"

    @property
    def project_root(self) -> Path:
        return self.backend_root.parent

    @property
    def frontend_root(self) -> Path:
        return self.project_root / "frontend"

    @property
    def frontend_dist_dir(self) -> Path:
        return self.frontend_root / "dist"


def get_settings() -> AppSettings:
    settings = AppSettings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
