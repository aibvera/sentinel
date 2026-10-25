import { useCallback, useEffect, useState } from "react";
import { api, type Clip, type DaySummary, type Face, type HourActivity, type Status } from "./api";
import { Calendar } from "./components/Calendar";
import { ClipList } from "./components/ClipList";
import { FaceGallery } from "./components/FaceGallery";
import { Player } from "./components/Player";
import { Timeline } from "./components/Timeline";
import { duration, longDay } from "./format";

const REFRESH_MS = 10_000;

interface Route {
  day: string | null;
  clip: number | null;
  t: number | null;
}

/** La vista vive en el hash (#/2026-09-23/12?t=4.5) para poder compartir o recargar un momento exacto. */
function readRoute(): Route {
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const [day, clip] = path.split("/");
  const t = new URLSearchParams(query).get("t");
  return { day: /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : null, clip: clip ? Number(clip) : null, t: t ? Number(t) : null };
}

function writeRoute({ day, clip, t }: Route) {
  location.hash = `/${day ?? ""}${clip ? `/${clip}` : ""}${t != null ? `?t=${t}` : ""}`;
}

/** Ejecuta fn al montar, cuando cambian deps y cada REFRESH_MS, para ver los clips nuevos sin recargar. */
function usePolling(fn: () => void, deps: unknown[]) {
  useEffect(() => {
    fn();
    const id = setInterval(fn, REFRESH_MS);
    return () => clearInterval(id);
  }, deps);
}

export default function App() {
  const [route, setRoute] = useState(readRoute);
  const [days, setDays] = useState<DaySummary[] | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [hours, setHours] = useState<HourActivity[]>([]);
  const [faces, setFaces] = useState<Face[]>([]);
  const [hour, setHour] = useState<number | null>(null);
  const [onlyPersons, setOnlyPersons] = useState(true);
  const [tab, setTab] = useState<"clips" | "faces">("clips");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onHash = () => setRoute(readRoute());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  usePolling(() => {
    api.days().then(setDays, (e) => setError(String(e)));
    api.status().then(setStatus, () => setStatus(null));
  }, []);

  // Sin día en la URL se abre el más reciente con personas (o el más reciente).
  useEffect(() => {
    if (!route.day && days?.length) writeRoute({ day: (days.find((d) => d.person_clips > 0) ?? days[0]).day, clip: null, t: null });
  }, [days, route.day]);

  usePolling(() => {
    if (!route.day) return;
    const day = route.day;
    Promise.all([api.clips(day), api.timeline(day), api.faces(day)]).then(([c, h, f]) => {
      setClips(c);
      setHours(h);
      setFaces(f);
      setError(null);
    }, (e) => setError(String(e)));
  }, [route.day]);

  useEffect(() => setHour(null), [route.day]);

  const selectDay = useCallback((day: string) => writeRoute({ day, clip: null, t: null }), []);
  const selectClip = (clip: Clip, t: number | null = null) => writeRoute({ day: clip.day, clip: clip.id, t });

  const summary = days?.find((d) => d.day === route.day);
  const visible = clips.filter(
    (c) => (hour === null || Number(c.start_ts.slice(11, 13)) === hour) && (!onlyPersons || c.max_persons > 0 || c.status !== "done"),
  );
  const current = clips.find((c) => c.id === route.clip) ?? null;
  const index = current ? visible.findIndex((c) => c.id === current.id) : -1;
  const prev = index > 0 ? visible[index - 1] : null;
  const next = index >= 0 && index < visible.length - 1 ? visible[index + 1] : null;

  return (
    <div className="flex min-h-full flex-col">
      <header className="flex items-center gap-3 border-b border-slate-800 px-6 py-3">
        <img src="/favicon.svg" alt="" className="size-7" />
        <h1 className="text-lg font-semibold tracking-tight">Sentinel</h1>
        <div className="ml-auto text-xs text-slate-400">
          {status === null ? (
            <span className="text-red-400">api sin conexión</span>
          ) : status.pending > 0 ? (
            <span className="flex items-center gap-2">
              <span className="size-2 animate-pulse rounded-full bg-amber-400" />
              {status.pending} clip{status.pending === 1 ? "" : "s"} por analizar
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <span className="size-2 rounded-full bg-emerald-500" /> al día · {status.done} clips analizados
            </span>
          )}
        </div>
      </header>

      <div className="flex flex-1 flex-col gap-6 p-6 lg:flex-row">
        <aside className="w-full shrink-0 space-y-4 lg:w-72">
          {days && <Calendar days={days} selected={route.day} onSelect={selectDay} />}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-2">
            <h2 className="px-2 py-1 text-xs text-slate-500">Días con personas</h2>
            <ul className="max-h-80 overflow-y-auto">
              {days
                ?.filter((d) => d.person_clips > 0)
                .map((d) => (
                  <li key={d.day}>
                    <button
                      onClick={() => selectDay(d.day)}
                      className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm ${d.day === route.day ? "bg-slate-800 text-white" : "text-slate-300 hover:bg-slate-800/60"}`}
                    >
                      <span className="font-mono">{d.day}</span>
                      <span className="text-xs text-amber-300">{d.person_clips} clips</span>
                    </button>
                  </li>
                ))}
              {days?.every((d) => d.person_clips === 0) && <li className="px-2 py-1.5 text-sm text-slate-500">Todavía ninguno.</li>}
            </ul>
          </div>
        </aside>

        <main className="min-w-0 flex-1 space-y-5">
          {error && <p className="rounded-lg border border-red-900 bg-red-950/50 px-4 py-2 text-sm text-red-300">{error}</p>}
          {days?.length === 0 && <p className="py-20 text-center text-slate-500">Aún no hay videos grabados.</p>}

          {route.day && (
            <>
              <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
                <h2 className="text-2xl font-semibold first-letter:uppercase">{longDay(route.day)}</h2>
                {summary && (
                  <p className="text-sm text-slate-400">
                    {summary.clips} clips · <span className="text-amber-300">{summary.person_clips} con personas</span> ·{" "}
                    {duration(summary.person_seconds)} con personas · <span className="text-sky-300">{summary.faces} rostros</span>
                  </p>
                )}
              </div>

              <Timeline hours={hours} selected={hour} onSelect={setHour} />

              {current && <Player clip={current} seek={route.t} onPrev={prev ? () => selectClip(prev) : undefined} onNext={next ? () => selectClip(next) : undefined} />}

              <div className="flex items-center gap-1 border-b border-slate-800">
                {(["clips", "faces"] as const).map((name) => (
                  <button
                    key={name}
                    onClick={() => setTab(name)}
                    className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === name ? "border-amber-500 text-white" : "border-transparent text-slate-400 hover:text-slate-200"}`}
                  >
                    {name === "clips" ? `Clips (${visible.length})` : `Rostros (${faces.length})`}
                  </button>
                ))}
                {tab === "clips" && (
                  <label className="ml-auto flex cursor-pointer items-center gap-2 text-sm text-slate-400">
                    <input type="checkbox" checked={onlyPersons} onChange={(e) => setOnlyPersons(e.target.checked)} className="accent-amber-500" />
                    Solo con personas
                  </label>
                )}
              </div>

              {tab === "clips" ? (
                <ClipList clips={visible} selected={route.clip} onSelect={(c) => selectClip(c)} />
              ) : (
                <FaceGallery
                  faces={hour === null ? faces : faces.filter((f) => Number(f.ts.slice(11, 13)) === hour)}
                  onSelect={(f) => {
                    const clip = clips.find((c) => c.id === f.clip_id);
                    if (clip) selectClip(clip, Math.max(0, f.t - 0.5));
                  }}
                />
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
