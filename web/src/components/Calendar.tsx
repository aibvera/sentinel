import { useState } from "react";
import type { DaySummary } from "../api";
import { monthName, parseDay, toDay } from "../format";

const WEEK = ["L", "M", "X", "J", "V", "S", "D"];

interface Props {
  days: DaySummary[];
  selected: string | null;
  onSelect: (day: string) => void;
}

/** Calendario mensual: los días con video son clicables y los que tienen personas se marcan en ámbar. */
export function Calendar({ days, selected, onSelect }: Props) {
  const byDay = new Map(days.map((d) => [d.day, d]));
  const initial = selected ? parseDay(selected) : days[0] ? parseDay(days[0].day) : new Date();
  const [month, setMonth] = useState(new Date(initial.getFullYear(), initial.getMonth(), 1));

  const offset = (month.getDay() + 6) % 7; // Semana empieza el lunes.
  const total = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const cells = [...Array(offset).fill(null), ...Array.from({ length: total }, (_, i) => i + 1)];
  const today = toDay(new Date());
  const shift = (delta: number) => setMonth(new Date(month.getFullYear(), month.getMonth() + delta, 1));

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-3 flex items-center justify-between">
        <button className="rounded px-2 py-1 text-slate-400 hover:bg-slate-800 hover:text-white" onClick={() => shift(-1)} aria-label="Mes anterior">
          ‹
        </button>
        <span className="text-sm font-medium capitalize">{monthName(month)}</span>
        <button className="rounded px-2 py-1 text-slate-400 hover:bg-slate-800 hover:text-white" onClick={() => shift(1)} aria-label="Mes siguiente">
          ›
        </button>
      </div>
      <div className="grid grid-cols-7 gap-1 text-center text-xs">
        {WEEK.map((w) => (
          <span key={w} className="pb-1 text-slate-500">
            {w}
          </span>
        ))}
        {cells.map((n, i) => {
          if (n === null) return <span key={`e${i}`} />;
          const day = toDay(new Date(month.getFullYear(), month.getMonth(), n));
          const info = byDay.get(day);
          const persons = (info?.person_clips ?? 0) > 0;
          const isSelected = day === selected;
          return (
            <button
              key={day}
              disabled={!info}
              onClick={() => onSelect(day)}
              title={info ? `${info.clips} clips · ${info.person_clips} con personas · ${info.faces} rostros` : undefined}
              className={[
                "relative aspect-square rounded-md text-sm transition",
                !info && "cursor-default text-slate-700",
                info && !isSelected && "text-slate-200 hover:bg-slate-800",
                info && !persons && "bg-slate-800/40",
                persons && !isSelected && "bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/40",
                isSelected && "bg-amber-500 font-semibold text-slate-950",
                day === today && !isSelected && "underline underline-offset-4",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              {n}
            </button>
          );
        })}
      </div>
      <div className="mt-3 flex gap-4 text-[11px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <i className="inline-block size-2.5 rounded-sm bg-slate-700" /> con video
        </span>
        <span className="flex items-center gap-1.5">
          <i className="inline-block size-2.5 rounded-sm bg-amber-500/60" /> con personas
        </span>
      </div>
    </div>
  );
}
