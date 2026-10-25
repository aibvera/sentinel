"""API HTTP de Sentinel: días, clips, detecciones, rostros y streaming de video."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path as PathParam
from fastapi.responses import FileResponse

from .config import Settings, load_settings, setup_logging
from .db import Database
from .detector import ClipAnalyzer
from .worker import Worker

log = logging.getLogger("api")

Day = Annotated[str, PathParam(pattern=r"^\d{4}-\d{2}-\d{2}$")]

CLIP_COLUMNS = """id, path, day, start_ts, status, error, duration, fps, width, height,
    max_persons, person_seconds, first_person, face_count, processed_at, processing_ms"""


def _with_ts(row: dict, start_ts: str) -> dict:
    """Agrega la hora absoluta (ts) de una detección o rostro a partir del inicio del clip."""
    start = datetime.fromisoformat(start_ts)
    row["ts"] = (start + timedelta(seconds=row["t"])).strftime("%Y-%m-%dT%H:%M:%S")
    return row


def create_app(settings: Settings | None = None, analyzer: ClipAnalyzer | None = None) -> FastAPI:
    """Construye la app; el worker corre como hilo dentro del mismo proceso (único escritor de la base)."""
    settings = settings or load_settings()
    setup_logging(settings)
    db = Database(settings.db_path)
    worker = Worker(settings, db, analyzer) if settings.worker_enabled else None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if worker:
            worker.start()
        yield
        if worker:
            worker.stop()
        db.close()

    app = FastAPI(title="Sentinel", lifespan=lifespan)
    app.state.db = db
    app.state.worker = worker

    def file_or_404(path: Path, media_type: str) -> FileResponse:
        """Devuelve el archivo (con soporte de Range) o 404 si ya no existe."""
        if not path.is_file():
            raise HTTPException(404, "archivo no encontrado")
        return FileResponse(path, media_type=media_type)

    def clip_or_404(clip_id: int) -> dict:
        """Busca un clip por id."""
        clip = db.one(f"SELECT {CLIP_COLUMNS} FROM clips WHERE id = ?", (clip_id,))
        if clip is None:
            raise HTTPException(404, "clip no encontrado")
        return clip

    @app.get("/api/status")
    def status() -> dict:
        """Estado del procesamiento."""
        counts = {row["status"]: row["n"] for row in db.query("SELECT status, COUNT(*) n FROM clips GROUP BY status")}
        return {
            "worker": worker is not None,
            "current": worker.current if worker else None,
            "pending": counts.get("pending", 0),
            "done": counts.get("done", 0),
            "error": counts.get("error", 0),
        }

    @app.get("/api/days")
    def days() -> list[dict]:
        """Días con videos, del más reciente al más antiguo, con resumen de personas y rostros."""
        return db.query(
            """SELECT day, COUNT(*) clips,
                      SUM(max_persons > 0) person_clips,
                      SUM(person_seconds) person_seconds,
                      SUM(face_count) faces,
                      SUM(status = 'pending') pending
               FROM clips GROUP BY day ORDER BY day DESC"""
        )

    @app.get("/api/days/{day}/clips")
    def day_clips(day: Day) -> list[dict]:
        """Clips de un día en orden cronológico."""
        return db.query(f"SELECT {CLIP_COLUMNS} FROM clips WHERE day = ? ORDER BY start_ts", (day,))

    @app.get("/api/days/{day}/timeline")
    def day_timeline(day: Day) -> list[dict]:
        """Actividad por hora (0-23): clips, clips con personas y segundos con personas."""
        rows = db.query(
            """SELECT CAST(substr(start_ts, 12, 2) AS INTEGER) hour, COUNT(*) clips,
                      SUM(max_persons > 0) person_clips, SUM(person_seconds) person_seconds,
                      SUM(face_count) faces
               FROM clips WHERE day = ? GROUP BY hour""",
            (day,),
        )
        by_hour = {row["hour"]: row for row in rows}
        empty = {"clips": 0, "person_clips": 0, "person_seconds": 0, "faces": 0}
        return [by_hour.get(hour, {"hour": hour, **empty}) for hour in range(24)]

    @app.get("/api/days/{day}/faces")
    def day_faces(day: Day) -> list[dict]:
        """Rostros detectados en un día, en orden cronológico."""
        rows = db.query(
            """SELECT f.id, f.clip_id, f.t, f.conf, c.start_ts FROM faces f JOIN clips c ON c.id = f.clip_id
               WHERE c.day = ? ORDER BY c.start_ts, f.t""",
            (day,),
        )
        return [_with_ts(row, row.pop("start_ts")) for row in rows]

    @app.get("/api/clips/{clip_id}")
    def clip_detail(clip_id: int) -> dict:
        """Un clip con todas sus cajas de personas y sus rostros."""
        clip = clip_or_404(clip_id)
        clip["detections"] = db.query(
            "SELECT t, conf, x1, y1, x2, y2 FROM detections WHERE clip_id = ? ORDER BY t", (clip_id,),
        )
        clip["faces"] = [
            _with_ts(row, clip["start_ts"])
            for row in db.query("SELECT id, t, conf, x1, y1, x2, y2 FROM faces WHERE clip_id = ? ORDER BY t", (clip_id,))
        ]
        return clip

    @app.get("/api/clips/{clip_id}/video")
    def clip_video(clip_id: int) -> FileResponse:
        """El mp4 original, servido con soporte de Range para poder adelantar en el reproductor."""
        return file_or_404(settings.recordings_path / clip_or_404(clip_id)["path"], "video/mp4")

    @app.get("/api/clips/{clip_id}/thumb")
    def clip_thumb(clip_id: int) -> FileResponse:
        """Miniatura del clip (el frame con la persona más clara, o el primero)."""
        clip_or_404(clip_id)
        return file_or_404(settings.thumbs_dir / f"{clip_id}.jpg", "image/jpeg")

    @app.get("/api/faces/{face_id}/image")
    def face_image(face_id: int) -> FileResponse:
        """Recorte JPG de un rostro."""
        face = db.one("SELECT file FROM faces WHERE id = ?", (face_id,))
        if face is None:
            raise HTTPException(404, "rostro no encontrado")
        return file_or_404(settings.faces_dir / face["file"], "image/jpeg")

    return app
