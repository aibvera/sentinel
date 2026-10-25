"""Persistencia en SQLite de clips, detecciones de personas y rostros."""

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id             INTEGER PRIMARY KEY,
    path           TEXT NOT NULL UNIQUE,  -- relativa a RECORDINGS_PATH, p. ej. 2026-09-23/22-38-08.mp4
    day            TEXT NOT NULL,         -- AAAA-MM-DD
    start_ts       TEXT NOT NULL,         -- AAAA-MM-DDTHH:MM:SS (hora local de la cámara)
    size           INTEGER NOT NULL,
    mtime          REAL NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | done | error
    error          TEXT,
    duration       REAL,
    fps            REAL,
    width          INTEGER,
    height         INTEGER,
    max_persons    INTEGER NOT NULL DEFAULT 0,
    person_seconds REAL NOT NULL DEFAULT 0,
    first_person   REAL,                  -- segundo del clip con la primera persona
    face_count     INTEGER NOT NULL DEFAULT 0,
    processed_at   TEXT,
    processing_ms  INTEGER
);
CREATE INDEX IF NOT EXISTS clips_day ON clips(day, start_ts);

CREATE TABLE IF NOT EXISTS detections (
    id      INTEGER PRIMARY KEY,
    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    t       REAL NOT NULL,                -- segundo dentro del clip
    conf    REAL NOT NULL,
    x1 INTEGER NOT NULL, y1 INTEGER NOT NULL, x2 INTEGER NOT NULL, y2 INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS detections_clip ON detections(clip_id, t);

CREATE TABLE IF NOT EXISTS faces (
    id      INTEGER PRIMARY KEY,
    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    t       REAL NOT NULL,
    conf    REAL NOT NULL,
    x1 INTEGER NOT NULL, y1 INTEGER NOT NULL, x2 INTEGER NOT NULL, y2 INTEGER NOT NULL,
    file    TEXT NOT NULL                 -- relativa a DATA_PATH/faces
);
CREATE INDEX IF NOT EXISTS faces_clip ON faces(clip_id, t);
"""


class Database:
    """Conexión única protegida por un lock: la api es el único proceso que escribe."""

    def __init__(self, path: Path):
        """Abre (o crea) la base y aplica el esquema."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        # journal_mode DELETE (no WAL): WAL usa memoria compartida, que no funciona bien sobre
        # bind mounts de Docker Desktop, y así la base se puede leer desde el host sin sorpresas.
        self._conn.execute("PRAGMA journal_mode=DELETE")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        """Ejecuta una consulta de lectura y devuelve las filas como diccionarios."""
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, tuple(params))]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        """Devuelve la primera fila de la consulta, o None."""
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Ejecuta una escritura y devuelve el id de la última fila insertada."""
        with self._lock, self._conn:
            return self._conn.execute(sql, tuple(params)).lastrowid

    def execute_many(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        """Ejecuta la misma escritura para varias filas en una sola transacción."""
        with self._lock, self._conn:
            self._conn.executemany(sql, (tuple(row) for row in rows))

    def save_results(self, clip_id: int, clip: dict, detections: list[tuple], faces: list[tuple]) -> None:
        """Reemplaza, en una sola transacción, los resultados de un clip procesado."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM detections WHERE clip_id = ?", (clip_id,))
            self._conn.execute("DELETE FROM faces WHERE clip_id = ?", (clip_id,))
            self._conn.executemany(
                "INSERT INTO detections (clip_id, t, conf, x1, y1, x2, y2) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(clip_id, *d) for d in detections],
            )
            self._conn.executemany(
                "INSERT INTO faces (clip_id, t, conf, x1, y1, x2, y2, file) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(clip_id, *f) for f in faces],
            )
            columns = ", ".join(f"{key} = ?" for key in clip)
            self._conn.execute(f"UPDATE clips SET {columns} WHERE id = ?", (*clip.values(), clip_id))

    def close(self) -> None:
        """Cierra la conexión."""
        with self._lock:
            self._conn.close()
