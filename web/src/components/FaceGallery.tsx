import { faceUrl, type Face } from "../api";
import { clock } from "../format";

interface Props {
  faces: Face[];
  onSelect: (face: Face) => void;
}

/** Todos los rostros del día; al hacer clic se abre el clip en ese instante. */
export function FaceGallery({ faces, onSelect }: Props) {
  if (faces.length === 0) return <p className="py-10 text-center text-sm text-slate-500">No se detectaron rostros este día.</p>;

  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(96px,1fr))] gap-3">
      {faces.map((face) => (
        <button key={face.id} onClick={() => onSelect(face)} className="group text-center" title={`Confianza ${Math.round(face.conf * 100)}%`}>
          <img
            src={faceUrl(face.id)}
            alt={`Rostro a las ${clock(face.ts)}`}
            loading="lazy"
            className="aspect-square w-full rounded-lg object-cover ring-1 ring-slate-800 transition group-hover:ring-2 group-hover:ring-sky-400"
          />
          <span className="font-mono text-[11px] text-slate-400">{clock(face.ts)}</span>
        </button>
      ))}
    </div>
  );
}
