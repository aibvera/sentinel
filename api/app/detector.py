"""Detección de personas (YOLO11n) y rostros (YuNet) sobre los frames de un clip."""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

log = logging.getLogger("detector")

YOLO_MODEL = "yolo11n.onnx"
YUNET_MODEL = "face_detection_yunet_2023mar.onnx"
YOLO_SIZE = 640
NMS_IOU = 0.45
# Los rostros se buscan solo en la parte superior del cuerpo; los recortes chicos se agrandan
# hasta este lado mínimo para que YuNet alcance a ver caras lejanas.
FACE_REGION = 0.6
FACE_MIN_SIDE = 224
THUMB_WIDTH = 480

Box = tuple[int, int, int, int]


class PersonDetector:
    """YOLO11n exportado a ONNX; solo se usa la clase 0 (persona) de COCO."""

    def __init__(self, model: Path, conf: float, threads: int):
        """Carga el modelo en CPU con un número fijo de hilos para no acaparar la máquina."""
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name
        self._conf = conf

    def detect(self, frame: np.ndarray) -> list[tuple[float, Box]]:
        """Devuelve (confianza, caja) de cada persona en coordenadas del frame original."""
        height, width = frame.shape[:2]
        scale = min(YOLO_SIZE / height, YOLO_SIZE / width)
        new_w, new_h = round(width * scale), round(height * scale)
        pad_x, pad_y = (YOLO_SIZE - new_w) // 2, (YOLO_SIZE - new_h) // 2
        canvas = np.full((YOLO_SIZE, YOLO_SIZE, 3), 114, dtype=np.uint8)
        canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = cv2.resize(frame, (new_w, new_h))
        blob = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0

        output = self._session.run(None, {self._input: blob})[0][0].T  # (8400, 4 + 80 clases)
        scores = output[:, 4]
        keep = scores >= self._conf
        if not keep.any():
            return []
        scores = scores[keep]
        cx, cy, w, h = output[keep, :4].T
        x1 = (cx - w / 2 - pad_x) / scale
        y1 = (cy - h / 2 - pad_y) / scale
        boxes = np.stack([x1, y1, w / scale, h / scale], axis=1)

        results = []
        for i in np.array(cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), self._conf, NMS_IOU)).flatten():
            bx, by, bw, bh = boxes[i]
            box = _clip_box(bx, by, bx + bw, by + bh, width, height)
            if box[2] > box[0] and box[3] > box[1]:
                results.append((float(scores[i]), box))
        return results


class FaceDetector:
    """YuNet de OpenCV aplicado sobre la región superior de cada persona detectada."""

    def __init__(self, model: Path, conf: float):
        """Carga el modelo YuNet."""
        self._detector = cv2.FaceDetectorYN.create(str(model), "", (320, 320), conf, 0.3, 20)

    def detect(self, frame: np.ndarray, person: Box) -> list[tuple[float, Box]]:
        """Busca rostros dentro de la persona y devuelve (confianza, caja) en coordenadas del frame."""
        x1, y1, x2, y2 = person
        y2 = y1 + max(1, round((y2 - y1) * FACE_REGION))
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return []
        factor = max(1.0, FACE_MIN_SIDE / min(crop.shape[:2]))
        if factor > 1:
            crop = cv2.resize(crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_LINEAR)
        self._detector.setInputSize((crop.shape[1], crop.shape[0]))
        _, faces = self._detector.detect(crop)
        if faces is None:
            return []
        height, width = frame.shape[:2]
        results = []
        for face in faces:
            fx, fy, fw, fh = face[:4] / factor
            box = _clip_box(x1 + fx, y1 + fy, x1 + fx + fw, y1 + fy + fh, width, height)
            if box[2] > box[0] and box[3] > box[1]:
                results.append((float(face[-1]), box))
        return results


@dataclass
class FaceCrop:
    """Rostro encontrado en un clip, con su imagen recortada."""

    t: float
    conf: float
    box: Box
    image: np.ndarray


@dataclass
class ClipResult:
    """Resultado de analizar un clip completo."""

    duration: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    detections: list[tuple[float, float, Box]] = field(default_factory=list)  # (t, conf, caja)
    faces: list[FaceCrop] = field(default_factory=list)
    thumbnail: np.ndarray | None = None
    elapsed_ms: int = 0

    @property
    def max_persons(self) -> int:
        """Mayor cantidad de personas vistas a la vez en un frame."""
        counts: dict[float, int] = {}
        for t, _, _ in self.detections:
            counts[t] = counts.get(t, 0) + 1
        return max(counts.values(), default=0)

    def person_seconds(self, sample_fps: float) -> float:
        """Segundos aproximados con al menos una persona en imagen."""
        return round(len({t for t, _, _ in self.detections}) / sample_fps, 1)


class ClipAnalyzer:
    """Recorre un clip muestreando frames y aplica ambos detectores."""

    def __init__(self, models_path: Path, sample_fps: float, person_conf: float, face_conf: float,
                 face_interval: float, threads: int):
        """Carga los modelos una sola vez."""
        cv2.setNumThreads(max(1, threads // 2))
        self._persons = PersonDetector(models_path / YOLO_MODEL, person_conf, threads)
        self._faces = FaceDetector(models_path / YUNET_MODEL, face_conf)
        self._sample_fps = sample_fps
        self._face_interval = face_interval

    def analyze(self, path: Path) -> ClipResult:
        """Analiza el clip; lanza OSError si no se puede abrir."""
        started = time.monotonic()
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise OSError(f"no se pudo abrir el video {path}")

        fps = capture.get(cv2.CAP_PROP_FPS)
        if not 1 <= fps <= 120:
            fps = 15.0  # Algunos mp4 fragmentados no informan bien su fps.
        step = max(1, round(fps / self._sample_fps))
        result = ClipResult(fps=round(fps, 3))
        # Por cada ventana de FACE_INTERVAL_SECONDS se guardan los mejores rostros, para no repetir decenas.
        face_buckets: dict[int, list[FaceCrop]] = {}
        best_conf = -1.0
        index = 0
        try:
            while True:
                if index % step:
                    if not capture.grab():
                        break
                    index += 1
                    continue
                ok, frame = capture.read()
                if not ok:
                    break
                t = round(index / fps, 2)
                index += 1
                if result.thumbnail is None:
                    result.height, result.width = frame.shape[:2]
                    result.thumbnail = frame

                frame_faces = []
                for conf, box in self._persons.detect(frame):
                    result.detections.append((t, conf, box))
                    if conf > best_conf:
                        best_conf, result.thumbnail = conf, frame
                    for face_conf, face_box in self._faces.detect(frame, box):
                        frame_faces.append(FaceCrop(t, face_conf, face_box, _face_image(frame, face_box)))
                if frame_faces:
                    # Por ventana se conservan los rostros del frame con el rostro más claro: uno por
                    # persona visible en ese frame, en vez de la misma cara repetida en cada muestra.
                    window = int(t // self._face_interval)
                    best = face_buckets.get(window)
                    if best is None or max(f.conf for f in frame_faces) > max(f.conf for f in best):
                        face_buckets[window] = frame_faces
        finally:
            capture.release()

        result.duration = round(index / fps, 2)
        result.faces = [face for bucket in face_buckets.values() for face in bucket]
        result.faces.sort(key=lambda f: f.t)
        if result.thumbnail is not None:
            result.thumbnail = _resize_width(result.thumbnail, THUMB_WIDTH)
        result.elapsed_ms = round((time.monotonic() - started) * 1000)
        return result


def _clip_box(x1: float, y1: float, x2: float, y2: float, width: int, height: int) -> Box:
    """Redondea la caja y la ajusta a los bordes de la imagen."""
    return (
        int(min(max(x1, 0), width)), int(min(max(y1, 0), height)),
        int(min(max(x2, 0), width)), int(min(max(y2, 0), height)),
    )


def _face_image(frame: np.ndarray, box: Box) -> np.ndarray:
    """Recorta el rostro con un margen del 30 % para que se vea la cabeza completa."""
    x1, y1, x2, y2 = box
    margin_x, margin_y = round((x2 - x1) * 0.3), round((y2 - y1) * 0.3)
    height, width = frame.shape[:2]
    crop = frame[max(0, y1 - margin_y):min(height, y2 + margin_y), max(0, x1 - margin_x):min(width, x2 + margin_x)]
    return crop.copy()


def _resize_width(image: np.ndarray, width: int) -> np.ndarray:
    """Reduce la imagen a un ancho máximo manteniendo la proporción."""
    if image.shape[1] <= width:
        return image
    return cv2.resize(image, (width, round(image.shape[0] * width / image.shape[1])), interpolation=cv2.INTER_AREA)
