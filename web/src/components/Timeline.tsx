import type { HourActivity } from "../api";

interface Props {
  hours: HourActivity[];
  selected: number | null;
  onSelect: (hour: number | null) => void;
}

/** Barras de 24 horas: la altura gris son los clips y la parte ámbar los segundos con personas. */
export function Timeline({ hours, selected, onSelect }: Props) {
  const maxClips = Math.max(1, ...hours.map((h) => h.clips));
  const maxPersons = Math.max(1, ...hours.map((h) => h.person_seconds));

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-2 flex items-center justify-between text-xs text-slate-400">
        <span>Actividad por hora</span>
        {selected !== null && (
          <button className="text-amber-400 hover:underline" onClick={() => onSelect(null)}>
            Ver todo el día
          </button>
        )}
      </div>
      <div className="flex h-24 items-end gap-[3px]">
        {hours.map((h) => {
          const active = selected === h.hour;
          return (
            <button
              key={h.hour}
              disabled={h.clips === 0}
              onClick={() => onSelect(active ? null : h.hour)}
              title={`${String(h.hour).padStart(2, "0")}:00 · ${h.clips} clips · ${h.person_clips} con personas · ${Math.round(h.person_seconds)} s con personas`}
              className={`group relative flex h-full flex-1 flex-col justify-end rounded-sm ${active ? "bg-slate-700/60" : "hover:bg-slate-800/60"} disabled:cursor-default disabled:hover:bg-transparent`}
            >
              <span className="w-full rounded-t-sm bg-slate-600/70" style={{ height: `${(h.clips / maxClips) * 45}%` }} />
              {h.person_seconds > 0 && (
                <span className="w-full bg-amber-500" style={{ height: `${Math.max(6, (h.person_seconds / maxPersons) * 55)}%` }} />
              )}
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex text-[10px] text-slate-500">
        {hours.map((h) => (
          <span key={h.hour} className="flex-1 text-center">
            {h.hour % 3 === 0 ? String(h.hour).padStart(2, "0") : ""}
          </span>
        ))}
      </div>
    </div>
  );
}
