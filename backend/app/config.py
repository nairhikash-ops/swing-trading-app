import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    data_dir: Path = Path(os.getenv("DATA_DIR", "./data"))
    backend_cors_origins: str = os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:5173")
    bhavcopy_target_sessions: int = int(os.getenv("BHAVCOPY_TARGET_SESSIONS", "210"))
    bhavcopy_max_file_bytes: int = int(os.getenv("BHAVCOPY_MAX_FILE_BYTES", "25000000"))
    bhavcopy_import_inbox_path: str = os.getenv("BHAVCOPY_IMPORT_INBOX_PATH", "")

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.backend_cors_origins.split(",") if item.strip()]

    @property
    def database_path(self) -> Path:
        return self.data_dir / "bhavcopy.sqlite3"

    @property
    def source_file_dir(self) -> Path:
        return self.data_dir / "bhavcopy_files"

    @property
    def import_inbox_dir(self) -> Path:
        if self.bhavcopy_import_inbox_path.strip():
            return Path(self.bhavcopy_import_inbox_path)
        return self.data_dir / "bhavcopy_inbox"


@lru_cache
def get_settings() -> Settings:
    return Settings()
