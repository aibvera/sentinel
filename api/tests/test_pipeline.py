"""Prueba de extremo a extremo: escaneo, análisis con los modelos reales y endpoints."""

import os
import shutil
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app

SAMPLES = Path(os.environ.get("SAMPLE_CLIPS", Path(__file__).resolve().parents[2] / "recordings"))
MODELS = Path(__file__).resolve().parents[1] / "models"
# Se analizan solo los clips más antiguos: recordings/ puede tener miles y nunca se están grabando.
MAX_SAMPLES = int(os.environ.get("MAX_SAMPLES", "8"))

pytestmark = pytest.mark.skipif(
    not any(SAMPLES.glob("*/*.mp4")) or not (MODELS / "yolo11n.onnx").exists(),
    reason="faltan clips en recordings/ (o SAMPLE_CLIPS) o modelos",
)


@pytest.fixture
def app(tmp_path):
    """App con una copia de los clips de muestra y el worker manejado a mano."""
    recordings = tmp_path / "recordings"
    old = time.time() - 3600
    for source in sorted(SAMPLES.glob("*/*.mp4"))[:MAX_SAMPLES]:
        clip = recordings / source.parent.name / source.name
        clip.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, clip)
        os.utime(clip, (old, old))  # Ya "terminaron de grabarse".
    settings = replace(
        load_settings(), recordings_path=recordings, data_path=tmp_path / "data", models_path=MODELS,
    )
    return create_app(settings)


def test_pipeline(app):
    worker = app.state.worker
    s = worker._settings
    worker.load_models()
    worker.scan()
    processed = 0
    while worker.process_next():
        processed += 1
    total = len(list(s.recordings_path.glob("*/*.mp4")))
    assert processed == total

    client = TestClient(app)
    status = client.get("/api/status").json()
    assert status["pending"] == 0 and status["done"] == total and status["error"] == 0

    days = client.get("/api/days").json()
    assert days and days[0]["clips"] > 0
    day = days[0]["day"]

    clips = client.get(f"/api/days/{day}/clips").json()
    timeline = client.get(f"/api/days/{day}/timeline").json()
    assert len(timeline) == 24 and sum(h["clips"] for h in timeline) == len(clips)

    clip = clips[0]
    detail = client.get(f"/api/clips/{clip['id']}").json()
    assert detail["duration"] > 0 and detail["width"] > 0

    video = client.get(f"/api/clips/{clip['id']}/video", headers={"Range": "bytes=0-99"})
    assert video.status_code == 206 and len(video.content) == 100
    assert client.get(f"/api/clips/{clip['id']}/thumb").status_code == 200

    for face in client.get(f"/api/days/{day}/faces").json()[:3]:
        assert client.get(f"/api/faces/{face['id']}/image").headers["content-type"] == "image/jpeg"

    # Si el recorder borra un clip, desaparece de la base en el siguiente escaneo.
    (s.recordings_path / clip["path"]).unlink()
    worker.scan()
    assert client.get(f"/api/clips/{clip['id']}").status_code == 404

    for c in clips:
        print(c["start_ts"], c["duration"], "s", c["max_persons"], "personas", c["face_count"], "rostros", c["processing_ms"], "ms")


def test_clip_changed_after_scan(app):
    """Un clip que cambia después del escaneo se reanaliza una vez, sin quedar en un bucle."""
    worker = app.state.worker
    s = worker._settings
    worker.load_models()
    worker.scan()
    total = len(list(s.recordings_path.glob("*/*.mp4")))
    # Como si el recorder lo hubiera seguido grabando después del escaneo.
    clip = next(s.recordings_path.glob("*/*.mp4"))
    later = time.time() - 1800
    os.utime(clip, (later, later))

    for _ in range(total + 2):
        if not worker.process_next():
            break
    else:
        pytest.fail("process_next no terminó: el clip cambiado se reintenta sin fin")
    status = TestClient(app).get("/api/status").json()
    assert status["pending"] == 0 and status["done"] == total


def test_bad_day(app):
    assert TestClient(app).get("/api/days/../clips").status_code == 404
    assert TestClient(app).get("/api/days/2026-1-1/clips").status_code == 422
