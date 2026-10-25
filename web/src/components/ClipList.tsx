import { thumbUrl, type Clip } from "../api";
import { clock, duration } from "../format";

interface Props {
  clips: Clip[];
  selected: number | null;
  onSelect: (clip: Clip) => void;
}

/** Clips del día agrupados por hora, con miniatura y cantidad de personas y rostros. */
export function ClipList({ clips, selected, onSelect }: Props) {
  if (clips.length === 0) return <p className="py-10 text-center text-sm text-slate-500">No hay clips con este filtro.</p>;

  const groups = new Map<string, Clip[]>();
  for (const clip of clips) {
    const hour = clip.start_ts.slice(11, 13);
    groups.set(hour, [...(groups.get(hour) ?? []), clip]);
  }

  return (
    <div className="space-y-5">
      {[...groups].map(([hour, items]) => (
        <section key={hour}>
          <h3 className="mb-2 font-mono text-xs text-slate-500">{hour}:00</h3>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
            {items.map((clip) => (
              <button
                key={clip.id}
                onClick={() => onSelect(clip)}
                className={`overflow-hidden rounded-lg border text-left transition ${
                  clip.id === selected ? "border-amber-500 ring-1 ring-amber-500" : "border-slate-800 hover:border-slate-600"
                } bg-slate-900`}
              >
                <div className="relative aspect-video bg-slate-800">
                  {clip.status === "done" && <img src={thumbUrl(clip)} alt="" loading="lazy" className="size-full object-cover" />}
                  {clip.status === "pending" && (
                    <span className="absolute inset-0 grid place-items-center text-xs text-slate-400">
                      <span className="flex items-center gap-2">
                        <span className="size-3 animate-spin rounded-full border-2 border-slate-500 border-t-amber-400" /> analizando
                      </span>
                    </span>
                  )}
                  {clip.status === "error" && (
                    <span className="absolute inset-0 grid place-items-center px-2 text-center text-xs text-red-400" title={clip.error ?? ""}>
                      error al analizar
                    </span>
                  )}
                  <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 font-mono text-[10px]">{duration(clip.duration)}</span>
                </div>
                <div className="flex items-center gap-2 px-2 py-1.5 text-xs">
                  <span className="font-mono text-slate-200">{clock(clip.start_ts)}</span>
                  {clip.max_persons > 0 && (
                    <span className="rounded bg-amber-500/20 px-1.5 text-amber-300" title="personas a la vez (máximo)">
                      👤 {clip.max_persons}
                    </span>
                  )}
                  {clip.face_count > 0 && (
                    <span className="rounded bg-sky-500/20 px-1.5 text-sky-300" title="rostros guardados">
                      ☺ {clip.face_count}
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
