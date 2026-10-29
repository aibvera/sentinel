"""Worker que descubre clips nuevos en RECORDINGS_PATH y los analiza en segundo plano."""

import logging
import re
import shutil
import threading
import time
from datetime import datetime, tzinfo
from pathlib import Path

import cv2

from .config import Settings
from .db import Database
from .detector import ClipAnalyzer

log = logging.getLogger("worker")

DAY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CLIP_PATTERN = re.compile(r"^(\d{2})-(\d{2})-(\d{2})(?:_\d+)?$")


def clip_start(day: str, stem: str, mtime: float, timezone: tzinfo | None) -> str:
    """Hora de inicio del clip según su nombre (HH-MM-SS); si no se puede leer, usa la fecha de modificación."""
    match = CLIP_PATTERN.match(stem)
    if match:
        return f"{day}T{match[1]}:{match[2]}:{match[3]}"
    return datetime.fromtimestamp(mtime, timezone).strftime("%Y-%m-%dT%H:%M:%S")


class Worker:
    """Escanea la carpeta de videos cada SCAN_SECONDS y procesa los clips que ya terminaron de grabarse.

    Se escanea en vez de usar notificaciones del sistema de archivos porque inotify no siempre
    atraviesa los bind mounts (p. ej. Docker Desktop en Windows) y el escaneo de unos días de clips es barato.
    """

    def __init__(self, settings: Settings, db: Database, analyzer: ClipAnalyzer | None = None):
        """Prepara carpetas; el analizador (modelos) se carga al arrancar el hilo si no se entrega."""
        self._settings = settings
        self._db = db
        self._analyzer = analyzer
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.current: str | None = None
        settings.faces_dir.mkdir(parents=True, exist_ok=True)
        settings.thumbs_dir.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        """Lanza el hilo del worker."""
        self._thread = threading.Thread(target=self._run, name="worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Pide al hilo que termine y lo espera (termina el clip en curso primero)."""
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=60)

    def wake(self) -> None:
        """Adelanta el siguiente escaneo."""
        self._wake.set()

    def load_models(self) -> None:
        """Carga los modelos si todavía no se cargaron (tarda ~1 s)."""
        if self._analyzer is None:
            s = self._settings
            self._analyzer = ClipAnalyzer(
                s.models_path, s.sample_fps, s.person_conf, s.face_conf, s.face_interval_seconds, s.ort_threads,
            )

    def _run(self) -> None:
        """Bucle principal: escanear, procesar lo listo, esperar."""
        self.load_models()
        log.info("Worker iniciado sobre %s", self._settings.recordings_path)
        while not self._stop.is_set():
            try:
                self.scan()
                while not self._stop.is_set() and self.process_next():
                    pass
            except Exception:
                log.exception("Error inesperado en el worker")
            self._wake.wait(self._settings.scan_seconds)
            self._wake.clear()

    def scan(self) -> None:
        """Sincroniza la tabla de clips con los archivos en disco.

        Los cambios se escriben en una transacción por tipo: con miles de clips (el primer escaneo),
        una transacción por fila tarda minutos sobre un bind mount.
        """
        root = self._settings.recordings_path
        timezone = self._settings.timezone
        known = {row["path"]: row for row in self._db.query("SELECT id, path, size, mtime FROM clips")}
        seen = set()
        new, changed = [], []
        if root.is_dir():
            for day_dir in root.iterdir():
                if not (day_dir.is_dir() and DAY_PATTERN.match(day_dir.name)):
                    continue
                for path in day_dir.glob("*.mp4"):
                    try:
                        stat = path.stat()
                    except OSError:
                        continue  # Lo borró el recorder mientras se listaba.
                    rel = f"{day_dir.name}/{path.name}"
                    seen.add(rel)
                    row = known.get(rel)
                    if row is None:
                        new.append((rel, day_dir.name, clip_start(day_dir.name, path.stem, stat.st_mtime, timezone),
                                    stat.st_size, stat.st_mtime))
                        log.debug("Clip nuevo: %s", rel)
                    elif row["size"] != stat.st_size or row["mtime"] != stat.st_mtime:
                        # Sigue creciendo (o fue reemplazado): se vuelve a analizar cuando se estabilice.
                        changed.append((stat.st_size, stat.st_mtime, row["id"]))

        if new:
            self._db.execute_many("INSERT INTO clips (path, day, start_ts, size, mtime) VALUES (?, ?, ?, ?, ?)", new)
            log.info("%d clips nuevos por analizar", len(new))
        if changed:
            self._db.execute_many("UPDATE clips SET size = ?, mtime = ?, status = 'pending' WHERE id = ?", changed)

        gone = [row["id"] for rel, row in known.items() if rel not in seen]
        if gone:
            self._forget(gone)
            log.info("%d clips eliminados del disco", len(gone))

    def process_next(self) -> bool:
        """Procesa el clip pendiente más reciente que ya terminó de grabarse; False si no hay ninguno."""
        cutoff = time.time() - self._settings.stable_seconds
        row = self._db.one(
            "SELECT * FROM clips WHERE status = 'pending' AND mtime <= ? ORDER BY start_ts DESC LIMIT 1", (cutoff,),
        )
        if row is None:
            return False
        self._process(row)
        return True

    def _process(self, row: dict) -> None:
        """Analiza un clip y guarda sus detecciones, rostros y miniatura."""
        path = self._settings.recordings_path / row["path"]
        self.current = row["path"]
        try:
            result = self._analyzer.analyze(path)
            stat = path.stat()
        except Exception as exc:
            log.error("No se pudo analizar %s: %s", row["path"], exc)
            self._db.execute("UPDATE clips SET status = 'error', error = ? WHERE id = ?", (str(exc), row["id"]))
            return
        finally:
            self.current = None

        if stat.st_size != row["size"] or stat.st_mtime != row["mtime"]:
            # Se guarda el estado nuevo: con el viejo, process_next lo elegiría una y otra vez sin que
            # scan llegue a correr, y el reintento esperaría a que el clip se estabilice.
            self._db.execute(
                "UPDATE clips SET size = ?, mtime = ? WHERE id = ?", (stat.st_size, stat.st_mtime, row["id"]),
            )
            log.info("%s cambió durante el análisis; se reintentará", row["path"])
            return

        self._delete_files(row["id"])
        faces = []
        face_dir = self._settings.faces_dir / row["day"]
        face_dir.mkdir(parents=True, exist_ok=True)
        for n, face in enumerate(result.faces):
            name = f"{row['day']}/{row['id']}_{n}.jpg"
            if face.image.size and cv2.imwrite(str(self._settings.faces_dir / name), face.image):
                faces.append((face.t, round(face.conf, 3), *face.box, name))
        if result.thumbnail is not None:
            cv2.imwrite(str(self._thumb_path(row["id"])), result.thumbnail, [cv2.IMWRITE_JPEG_QUALITY, 80])

        person_times = [t for t, _, _ in result.detections]
        self._db.save_results(
            row["id"],
            {
                "status": "done", "error": None, "duration": result.duration, "fps": result.fps,
                "width": result.width, "height": result.height, "max_persons": result.max_persons,
                "person_seconds": result.person_seconds(self._settings.sample_fps),
                "first_person": min(person_times) if person_times else None, "face_count": len(faces),
                "processed_at": self._settings.now().strftime("%Y-%m-%dT%H:%M:%S"), "processing_ms": result.elapsed_ms,
            },
            [(t, round(conf, 3), *box) for t, conf, box in result.detections],
            faces,
        )
        log.info(
            "Analizado %s: %.1f s de video, %d personas máx., %d rostros, en %.1f s",
            row["path"], result.duration, result.max_persons, len(faces), result.elapsed_ms / 1000,
        )

    def _thumb_path(self, clip_id: int) -> Path:
        """Ruta de la miniatura de un clip."""
        return self._settings.thumbs_dir / f"{clip_id}.jpg"

    def _delete_files(self, clip_id: int) -> None:
        """Borra recortes y miniatura de un clip (antes de reprocesarlo u olvidarlo)."""
        for face in self._db.query("SELECT file FROM faces WHERE clip_id = ?", (clip_id,)):
            (self._settings.faces_dir / face["file"]).unlink(missing_ok=True)
        self._thumb_path(clip_id).unlink(missing_ok=True)

    def _forget(self, clip_ids: list[int]) -> None:
        """Quita los clips que ya no existen en disco junto con sus archivos derivados."""
        for clip_id in clip_ids:
            self._delete_files(clip_id)
        self._db.execute_many("DELETE FROM clips WHERE id = ?", ((clip_id,) for clip_id in clip_ids))
        for day_dir in self._settings.faces_dir.iterdir():
            if day_dir.is_dir() and not any(day_dir.iterdir()):
                shutil.rmtree(day_dir, ignore_errors=True)
