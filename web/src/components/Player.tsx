import { useEffect, useRef, useState } from "react";
import { api, faceUrl, videoUrl, type Clip, type ClipDetail } from "../api";
import { clock, clockAt, duration } from "../format";

interface Props {
  clip: Clip;
  seek: number | null;
  onPrev?: () => void;
  onNext?: () => void;
}

// Una caja se dibuja si su frame muestreado está a menos de esto del instante actual.
const BOX_WINDOW = 0.6;

/** Reproductor del clip con cajas de personas superpuestas y marcadores de detecciones. */
export function Player({ clip, seek, onPrev, onNext }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [detail, setDetail] = useState<ClipDetail | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [current, setCurrent] = useState(0);
  const shown = useRef(0);
  const [length, setLength] = useState(clip.duration ?? 0);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    api.clip(clip.id).then((d) => !cancelled && setDetail(d));
    return () => {
      cancelled = true;
    };
  }, [clip.id, clip.processed_at]);

  useEffect(() => {
    if (seek !== null && video.current && video.current.readyState >= 1) video.current.currentTime = seek;
  }, [seek, clip.id]);

  // Dibuja las cajas en cada frame mientras el video avanza.
  useEffect(() => {
    let frame = 0;
    const draw = () => {
      const v = video.current;
      const c = canvas.current;
      if (v && c) {
        const rect = v.getBoundingClientRect();
        c.width = rect.width * devicePixelRatio;
        c.height = rect.height * devicePixelRatio;
        const ctx = c.getContext("2d")!;
        ctx.clearRect(0, 0, c.width, c.height);
        const srcW = detail?.width || v.videoWidth;
        const srcH = detail?.height || v.videoHeight;
        if (showBoxes && detail && srcW && srcH) {
          // object-contain: el video ocupa el máximo posible manteniendo su proporción.
          const scale = Math.min(c.width / srcW, c.height / srcH);
          const ox = (c.width - srcW * scale) / 2;
          const oy = (c.height - srcH * scale) / 2;
          const t = v.currentTime;
          let nearest = Infinity;
          for (const d of detail.detections) {
            const diff = Math.abs(d.t - t);
            if (diff < BOX_WINDOW) nearest = Math.min(nearest, diff);
          }
          ctx.lineWidth = 2 * devicePixelRatio;
          ctx.font = `${12 * devicePixelRatio}px ui-sans-serif, system-ui`;
          for (const d of detail.detections) {
            if (Math.abs(Math.abs(d.t - t) - nearest) > 0.01) continue;
            const x = ox + d.x1 * scale;
            const y = oy + d.y1 * scale;
            ctx.strokeStyle = "#f59e0b";
            ctx.strokeRect(x, y, (d.x2 - d.x1) * scale, (d.y2 - d.y1) * scale);
            const label = `persona ${Math.round(d.conf * 100)}%`;
            ctx.fillStyle = "#f59e0b";
            ctx.fillRect(x, y - 16 * devicePixelRatio, ctx.measureText(label).width + 8 * devicePixelRatio, 16 * devicePixelRatio);
            ctx.fillStyle = "#0f172a";
            ctx.fillText(label, x + 4 * devicePixelRatio, y - 4 * devicePixelRatio);
          }
          ctx.strokeStyle = "#38bdf8";
          for (const f of detail.faces) {
            if (Math.abs(Math.abs(f.t - t) - nearest) <= 0.01) ctx.strokeRect(ox + f.x1 * scale, oy + f.y1 * scale, (f.x2 - f.x1) * scale, (f.y2 - f.y1) * scale);
          }
        }
        // Solo se re-renderiza cuando el reloj cambia de forma visible.
        if (Math.abs(v.currentTime - shown.current) > 0.1) {
          shown.current = v.currentTime;
          setCurrent(v.currentTime);
        }
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [detail, showBoxes]);

  const goTo = (t: number) => {
    if (video.current) {
      video.current.currentTime = t;
      void video.current.play();
    }
  };

  const personTimes = [...new Set(detail?.detections.map((d) => d.t) ?? [])];
  const total = length || 1;

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="relative bg-black">
        <video
          key={clip.id}
          ref={video}
          src={videoUrl(clip.id)}
          controls
          autoPlay
          muted
          playsInline
          className="aspect-video w-full object-contain"
          onLoadedMetadata={(e) => {
            const v = e.currentTarget;
            if (Number.isFinite(v.duration)) setLength(v.duration);
            v.currentTime = seek ?? (clip.first_person ? Math.max(0, clip.first_person - 1) : 0);
          }}
          onEnded={onNext}
        />
        <canvas ref={canvas} className="pointer-events-none absolute inset-0 h-full w-full" />
      </div>

      {/* Franja de marcadores: ámbar = persona, celeste = rostro. Clic para saltar. */}
      <div
        className="relative h-6 cursor-pointer bg-slate-950"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          goTo(((e.clientX - rect.left) / rect.width) * total);
        }}
      >
        {personTimes.map((t) => (
          <span key={t} className="absolute top-1 h-4 w-[3px] -translate-x-1/2 rounded-full bg-amber-500/80" style={{ left: `${(t / total) * 100}%` }} />
        ))}
        {detail?.faces.map((f) => (
          <span key={f.id} className="absolute top-0 size-2 -translate-x-1/2 rounded-full bg-sky-400" style={{ left: `${(f.t / total) * 100}%` }} />
        ))}
        <span className="absolute inset-y-0 w-px bg-white/70" style={{ left: `${(current / total) * 100}%` }} />
      </div>

      <div className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
        <button className="rounded-md border border-slate-700 px-2 py-1 hover:bg-slate-800 disabled:opacity-30" disabled={!onPrev} onClick={onPrev}>
          ‹ Anterior
        </button>
        <button className="rounded-md border border-slate-700 px-2 py-1 hover:bg-slate-800 disabled:opacity-30" disabled={!onNext} onClick={onNext}>
          Siguiente ›
        </button>
        <span className="font-mono text-base text-white">{clockAt(clip.start_ts, current)}</span>
        <span className="text-slate-400">
          clip de las {clock(clip.start_ts)} · {duration(clip.duration)}
        </span>
        <label className="ml-auto flex cursor-pointer items-center gap-2 text-slate-400">
          <input type="checkbox" checked={showBoxes} onChange={(e) => setShowBoxes(e.target.checked)} className="accent-amber-500" />
          Mostrar detecciones
        </label>
        <a className="text-slate-400 hover:text-white" href={videoUrl(clip.id)} download={clip.path.replace("/", "_")}>
          Descargar
        </a>
      </div>

      {detail && detail.faces.length > 0 && (
        <div className="flex gap-2 overflow-x-auto border-t border-slate-800 px-4 py-3">
          {detail.faces.map((f) => (
            <button key={f.id} onClick={() => goTo(f.t)} className="shrink-0 text-center" title={`Ir a ${clock(f.ts)}`}>
              <img src={faceUrl(f.id)} alt="" className="size-16 rounded-md object-cover ring-1 ring-slate-700 hover:ring-sky-400" />
              <span className="font-mono text-[10px] text-slate-500">{clock(f.ts)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
