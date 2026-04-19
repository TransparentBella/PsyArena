from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    manifest_path: Path
    db_path: Path
    mode: str


def _get_env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return Path(raw)


def load_settings() -> Settings:
    data_dir = _get_env_path("DATA_DIR", Path("data")).resolve()
    manifest_path = _get_env_path("MANIFEST_PATH", data_dir / "manifest.json").resolve()
    db_path = _get_env_path("DB_PATH", data_dir / "app.db").resolve()
    mode = (os.getenv("MODE") or "both").strip().lower()
    if mode not in {"text", "audio", "both"}:
        raise ValueError("MODE must be one of: text, audio, both")
    return Settings(
        data_dir=data_dir,
        manifest_path=manifest_path,
        db_path=db_path,
        mode=mode,
    )

