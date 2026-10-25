# Sentinel

Videovigilancia sobre una cámara RTSP:
- Graba clips mp4 cuando detecta movimiento.
- En cuanto se cierra cada clip, detecta personas y rostros.
- Muestra todo en una web que se navega por día y hora.

## Estructura

```
sentinel/
├── recorder/           grabación por movimiento (cámara RTSP → mp4)
├── api/                detección de personas y rostros, SQLite y API HTTP
│   ├── app/
│   ├── models/         yolo11n.onnx, face_detection_yunet_2023mar.onnx
│   └── tests/
├── web/                interfaz React servida con nginx
├── docker-compose.yml
└── .env                configuración compartida por los tres servicios
```

| Servicio | Qué hace |
|---|---|
| `recorder` | Graba clips mp4 (H.264) solo cuando hay movimiento, en `HOST_RECORDINGS/AAAA-MM-DD/HH-MM-SS.mp4`, y borra los antiguos |
| `api` | FastAPI y, en un hilo del mismo proceso, el worker que analiza los clips (es el único que escribe en la base) |
| `web` | React + Vite + Tailwind servido con nginx, que reenvía `/api` a la api. Disponible en `http://localhost:8080` y, desde la red local, en `http://IP_DEL_EQUIPO:8080` |

## Recorder

| Archivo | Responsabilidad |
|---|---|
| `main.py` | Orquestador: inicializa todo y corre el loop eterno |
| `config.py` | Lee y valida el `.env` de la raíz; configura los logs (consola + un archivo por día) |
| `camera.py` | Conexión RTSP con timeouts y reconexión automática (backoff exponencial) |
| `motion.py` | % de disimilitud contra el frame anterior; hay movimiento si supera `DISIMIL_TH` |
| `recorder.py` | Abre y cierra clips con pre y post grabación, parte los clips largos y se recupera de fallas de ffmpeg o del disco |
| `storage.py` | Carpetas `AAAA-MM-DD/`, borrado por `ELIMINATION_DAYS` y por falta de espacio (`MIN_FREE_MB`) |
| `lifecycle.py` | Apagado ordenado (Ctrl+C / `docker stop`) y watchdog que reinicia el proceso si se congela |
| `alerts.py` | Aviso por Telegram si la cámara pasa `TELEGRAM_ALERT_MINUTES` sin imagen, y otro cuando vuelve |

- Los mp4 son **fragmentados**: si el proceso muere a mitad de una grabación, el archivo sigue siendo reproducible (se pierden como máximo ~2 s).
- Para calibrar `DISIMIL_TH`, usa `LOG_LEVEL=DEBUG`: cada frame con movimiento muestra su % de disimilitud.
- Cada día deja su log en `HOST_RECORDINGS/logs/AAAA-MM-DD.log`, que se borra tras `ELIMINATION_DAYS` igual que los videos.

### Alertas por Telegram
1. En Telegram, habla con **@BotFather**, envía `/newbot` y copia el token en `TELEGRAM_BOT_TOKEN`.
2. Abre el chat con tu bot nuevo y envíale cualquier mensaje (un bot no puede escribirte si tú no le escribes primero).
3. Abre `https://api.telegram.org/bot<TOKEN>/getUpdates` en el navegador y copia el número de `"chat":{"id":...}` en `TELEGRAM_CHAT_ID`.

Si el token o el chat id están mal, el log muestra `Telegram rechazó el mensaje` con el motivo. Si no hay internet, el aviso se reintenta hasta que salga.

## Detección (api)
1. El worker revisa `/recordings` cada `SCAN_SECONDS`. No usa inotify, que no atraviesa bien los bind mounts de Docker Desktop.
2. Un clip se analiza cuando lleva `STABLE_SECONDS` sin modificarse, es decir, cuando ya terminó de grabarse.
3. Se muestrean `SAMPLE_FPS` frames por segundo. **YOLO11n** (ONNX, solo en CPU) detecta personas y **YuNet** (OpenCV) busca rostros en la parte superior de cada persona.
4. Se guardan las cajas, los recortes de rostros (por cada ventana de `FACE_INTERVAL_SECONDS`, los del frame con el rostro más claro) y una miniatura del frame con la persona más clara.
5. Si el recorder borra un clip por antigüedad, sus datos se borran en el siguiente escaneo.

## Datos accesibles desde el host

```
HOST_RECORDINGS/            videos (los escribe el recorder; la api los monta en solo lectura)
├── AAAA-MM-DD/HH-MM-SS.mp4
└── logs/AAAA-MM-DD.log
HOST_DATA/
├── sentinel.db             SQLite: tablas clips, detections, faces
├── faces/AAAA-MM-DD/*.jpg  recortes de rostros
└── thumbs/<clip_id>.jpg    miniaturas
```

`sentinel.db` se puede abrir desde el host con DB Browser for SQLite, `sqlite3` o Python **para leer**. Para escribir, hazlo solo a través de la api, porque el bloqueo de archivos de SQLite no es fiable entre el host y un contenedor. La base usa `journal_mode=DELETE`, no WAL, por la misma razón.

Ejemplo: clips con personas de un día.

```sql
SELECT start_ts, max_persons, person_seconds, face_count FROM clips WHERE day = '2026-09-23' AND max_persons > 0;
```

## Configuración

Copia `.env.example` a `.env` y ajusta los valores (cada variable está comentada ahí). El mismo archivo lo usan el recorder, la api y `docker compose`.

## Docker

```bash
docker compose up -d --build
```

- Para usar solo la analítica sobre videos que ya existen: `docker compose up -d api web`.
- `ORT_THREADS` y `API_CPUS` (por defecto 4) limitan la CPU de la api para que el recorder nunca se quede sin ella.
- En Linux, pon `HOST_UID` y `HOST_GID` (salida de `id -u` / `id -g`) para que los archivos queden a tu nombre.
- Antes de arrancar recorder y api, el servicio `init` crea `HOST_RECORDINGS` y `HOST_DATA` si no existen y se las asigna a `HOST_UID:HOST_GID` (si las creara Docker, quedarían de root y la api no podría abrir la base).
- Si el puerto 8080 ya está ocupado en el equipo (`address already in use`), cambia `WEB_PORT` en `.env`.

Ver logs y detener:

```bash
docker compose logs -f recorder api
```

```bash
docker compose down
```

### Acceso desde otra PC de la red local

La web escucha en todas las interfaces del equipo (`0.0.0.0:8080`), así que cualquier PC o celular conectado a la misma red puede abrirla:

1. En el equipo donde corre Sentinel, busca su IP local: en Windows con `ipconfig` (la "Dirección IPv4" del adaptador Wi-Fi o Ethernet, p. ej. `192.168.1.41`); en Linux con `hostname -I`.
2. Desde la otra PC, abre `http://IP_DEL_EQUIPO:8080` (o el puerto que pongas en `WEB_PORT`).

Si no carga:
- **Windows:** la red del equipo debe ser **privada** (Configuración → Red e Internet → propiedades de la red). Docker Desktop crea al instalarse la regla de firewall que permite conexiones entrantes en redes privadas. Si falta, créala desde una PowerShell como administrador:

  ```powershell
  New-NetFirewallRule -DisplayName "Sentinel web" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Private
  ```

- **Linux:** si usas `ufw`, ejecuta `sudo ufw allow 8080/tcp`.
- Fija la IP del equipo en el router (reserva DHCP) para que la dirección no cambie.

> La web no tiene usuario ni contraseña: cualquiera en la red local puede ver los videos y los rostros. **No abras el puerto en el router hacia internet**; para entrar desde fuera de casa, usa una VPN (p. ej. WireGuard o Tailscale).

## Desarrollo local

Un solo `.venv` con Python 3.12 (creado desde el entorno conda `twelve`) sirve para los dos servicios Python. Las rutas relativas del `.env` (`SAVE_PATH`, `RECORDINGS_PATH`, `DATA_PATH`) se resuelven desde la raíz del repo, así que el recorder y la api comparten `./recordings`.

```bash
.venv/Scripts/python.exe -m pip install -r recorder/requirements.txt -r api/requirements-dev.txt
```

```bash
docker build --target models --output api/models api
```

```bash
.venv/Scripts/python.exe recorder/main.py
```

```bash
.venv/Scripts/python.exe -m uvicorn --app-dir api app.main:create_app --factory --reload
```

```bash
cd web && npm install && npm run dev
```

Pruebas (usan los `MAX_SAMPLES` clips más antiguos, 8 por defecto, de `recordings/` o de `SAMPLE_CLIPS`):

```bash
cd api && ../.venv/Scripts/python.exe -m pytest -s
```

## API

| Ruta | Devuelve |
|---|---|
| `GET /api/status` | clips pendientes, analizados y con error, y el clip en análisis |
| `GET /api/days` | días con resumen: clips, clips con personas, segundos con personas, rostros |
| `GET /api/days/{día}/clips` | clips del día |
| `GET /api/days/{día}/timeline` | actividad de las 24 horas |
| `GET /api/days/{día}/faces` | rostros del día, con su hora exacta |
| `GET /api/clips/{id}` | clip con todas sus cajas de personas y rostros |
| `GET /api/clips/{id}/video` | mp4 con soporte de Range |
| `GET /api/clips/{id}/thumb`, `GET /api/faces/{id}/image` | imágenes JPG |

## Modelos

Los modelos no están en git; se generan al construir la imagen de la api:

- `face_detection_yunet_2023mar.onnx`: se descarga de OpenCV Zoo (licencia MIT) y se verifica su SHA-256.
- `yolo11n.onnx`: se descargan los pesos oficiales de Ultralytics (licencia **AGPL-3.0**) y se exportan a ONNX.

De eso se encarga [api/models/download.py](api/models/download.py), en una etapa propia del `Dockerfile`. torch solo existe en esa etapa: la imagen final lleva únicamente los `.onnx`. El primer build descarga ~1 GB y tarda unos minutos; después queda en la caché de Docker. Una vez construida, la imagen no necesita internet para detectar.

Para desarrollo local, extrae los modelos de esa misma etapa (no hace falta instalar torch):

```bash
docker build --target models --output api/models api
```

## Adicionales

Descargar la carpeta de videos de un día desde un servidor Linux a un PC con Windows:

```bash
scp -r usuario@IP_DEL_SERVIDOR:~/sentinel/recordings/2026-09-23 "$env:USERPROFILE\Downloads\"
```

Descargar el log de un día:

```bash
scp usuario@IP_DEL_SERVIDOR:~/sentinel/recordings/logs/2026-09-23.log "$env:USERPROFILE\Downloads\"
```

Reemplaza `usuario`, `IP_DEL_SERVIDOR` y la fecha por los valores reales.
