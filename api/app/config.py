"""Configuración de la api leída de variables de entorno."""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
# Raíz del repo: .env compartido con el recorder; las rutas relativas se resuelven desde ahí.
ROOT_DIR = APP_DIR.parent


def _env(name: str, default: str) -> str:
    """Devuelve la variable de entorno o el valor por defecto si está vacía."""
    return os.environ.get(name, "").strip() or default


@dataclass(frozen=True)
class Settings:
    """Rutas, umbrales de detección y ritmo del worker."""

    recordings_path: Path
    data_path: Path
    models_path: Path
    sample_fps: float
    person_conf: float
    face_conf: float
    face_interval_seconds: float
    ort_threads: int
    scan_seconds: float
    stable_seconds: float
    worker_enabled: bool
    log_level: str
    timezone: tzinfo | None  # La misma TIMEZONE del recorder; None = hora local del sistema.

    def now(self) -> datetime:
        """Fecha y hora actual en la zona horaria configurada."""
        return datetime.now(self.timezone)

    @property
    def db_path(self) -> Path:
        """Ruta del archivo SQLite."""
        return self.data_path / "sentinel.db"

    @property
    def faces_dir(self) -> Path:
        """Carpeta de recortes de rostros."""
        return self.data_path / "faces"

    @property
    def thumbs_dir(self) -> Path:
        """Carpeta de miniaturas de clips."""
        return self.data_path / "thumbs"


def _path(name: str, default: str) -> Path:
    """Ruta de una variable de entorno; si es relativa, se toma desde la raíz del repo."""
    return (ROOT_DIR / _env(name, default)).resolve()


def load_settings() -> Settings:
    """Construye la configuración desde el entorno y el .env de la raíz (las variables ya definidas mandan)."""
    load_dotenv(ROOT_DIR / ".env")
    return Settings(
        recordings_path=_path("RECORDINGS_PATH", "recordings"),
        data_path=_path("DATA_PATH", "data"),
        models_path=_path("MODELS_PATH", str(APP_DIR / "models")),
        sample_fps=float(_env("SAMPLE_FPS", "2")),
        person_conf=float(_env("PERSON_CONF", "0.45")),
        face_conf=float(_env("FACE_CONF", "0.75")),
        face_interval_seconds=float(_env("FACE_INTERVAL_SECONDS", "2")),
        ort_threads=int(_env("ORT_THREADS", "4")),
        scan_seconds=float(_env("SCAN_SECONDS", "5")),
        stable_seconds=float(_env("STABLE_SECONDS", "15")),
        worker_enabled=_env("WORKER_ENABLED", "1") not in ("0", "false", "no"),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
        timezone=_timezone(_env("TIMEZONE", "")),
    )


def _timezone(name: str) -> tzinfo | None:
    """Zona horaria por nombre (p. ej. America/Bogota), o None si está vacía."""
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except Exception as exc:
        raise ValueError(f"Zona horaria inválida en TIMEZONE: {name!r} (ejemplo: America/Bogota)") from exc


def setup_logging(settings: Settings) -> None:
    """Configura los logs en consola con la hora de la zona configurada, igual que el recorder."""
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    formatter.converter = lambda ts: datetime.fromtimestamp(ts, settings.timezone).timetuple()
    handler.setFormatter(formatter)
    logging.basicConfig(level=settings.log_level, handlers=[handler], force=True)
