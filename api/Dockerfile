# --- Etapa 1: descarga YuNet y exporta YOLO11n a ONNX (torch solo vive en esta etapa) ---
FROM python:3.12-slim AS export

# ultralytics trae opencv-python con GUI, que necesita estas librerías del sistema.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /export
COPY models/requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY models/download.py .
RUN python download.py /out

# --- Etapa 2: solo los .onnx (sirve también para extraerlos: docker build --target models --output api/models api) ---
FROM scratch AS models
COPY --from=export /out/ /

# --- Etapa 3: imagen final de la api ---
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RECORDINGS_PATH=/recordings \
    DATA_PATH=/data \
    MODELS_PATH=/app/models

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=models / ./models
COPY app ./app

# Usuario sin privilegios; /recordings (solo lectura) y /data se montan desde carpetas del host.
RUN useradd --uid 1000 --no-create-home sentinel \
    && mkdir -p /recordings /data \
    && chown sentinel /data
USER sentinel

EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
