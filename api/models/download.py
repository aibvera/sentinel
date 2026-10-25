"""Obtiene los modelos de la api: descarga YuNet y exporta YOLO11n a ONNX.

Los modelos no se versionan en git: se generan al construir la imagen (etapa `models`
del Dockerfile). Para desarrollo local, lo más simple es extraerlos de esa etapa:

    docker build --target models --output api/models api

Uso directo (requiere `pip install -r requirements.txt` de esta carpeta, que incluye torch):

    python download.py [carpeta_destino]
"""

import hashlib
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

YUNET_NAME = "face_detection_yunet_2023mar.onnx"
YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/" + YUNET_NAME
)
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"

YOLO_NAME = "yolo11n.onnx"
YOLO_WEIGHTS = "yolo11n.pt"
YOLO_OUTPUT_SHAPE = [1, 84, 8400]  # 4 coordenadas + 80 clases COCO, 8400 anclas a 640x640.


def sha256(path: Path) -> str:
    """Hash SHA-256 de un archivo."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_yunet(dest: Path) -> None:
    """Descarga YuNet de OpenCV Zoo y verifica su hash."""
    target = dest / YUNET_NAME
    if target.exists() and sha256(target) == YUNET_SHA256:
        print(f"{YUNET_NAME}: ya existe")
        return
    tmp = target.with_suffix(".part")
    with urllib.request.urlopen(YUNET_URL, timeout=60) as response, tmp.open("wb") as file:
        shutil.copyfileobj(response, file)
    actual = sha256(tmp)
    if actual != YUNET_SHA256:
        tmp.unlink()
        sys.exit(f"{YUNET_NAME}: hash inesperado {actual}")
    tmp.replace(target)
    print(f"{YUNET_NAME}: descargado")


def check_yolo(path: Path) -> bool:
    """Comprueba que el ONNX carga y tiene la salida esperada."""
    import onnxruntime as ort

    try:
        session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    except Exception:
        return False
    return session.get_outputs()[0].shape == YOLO_OUTPUT_SHAPE


def get_yolo(dest: Path) -> None:
    """Descarga los pesos oficiales de YOLO11n (Ultralytics) y los exporta a ONNX."""
    target = dest / YOLO_NAME
    if target.exists() and check_yolo(target):
        print(f"{YOLO_NAME}: ya existe")
        return
    from ultralytics import YOLO

    # Se trabaja en una carpeta temporal para no dejar el .pt ni archivos intermedios en dest.
    with tempfile.TemporaryDirectory() as workdir:
        weights = Path(workdir) / YOLO_WEIGHTS
        exported = Path(YOLO(str(weights)).export(format="onnx", imgsz=640, opset=17, simplify=True))
        if not check_yolo(exported):
            sys.exit(f"{YOLO_NAME}: la exportación no tiene la salida {YOLO_OUTPUT_SHAPE}")
        shutil.move(exported, target)
    print(f"{YOLO_NAME}: exportado")


def main() -> None:
    """Deja ambos modelos en la carpeta indicada (por defecto, la de este script)."""
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent)
    dest.mkdir(parents=True, exist_ok=True)
    get_yunet(dest)
    get_yolo(dest)


if __name__ == "__main__":
    main()
