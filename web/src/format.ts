// Utilidades de formato de fechas y duraciones.

const MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const WEEKDAYS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];

export const parseDay = (day: string) => {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d);
};

export const toDay = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

export const longDay = (day: string) => {
  const date = parseDay(day);
  return `${WEEKDAYS[date.getDay()]} ${date.getDate()} de ${MONTHS[date.getMonth()]} de ${date.getFullYear()}`;
};

export const monthName = (date: Date) => `${MONTHS[date.getMonth()]} ${date.getFullYear()}`;

/** "2026-09-23T22:38:08" → "22:38:08" */
export const clock = (ts: string) => ts.slice(11, 19);

export const duration = (seconds: number | null) => {
  if (seconds == null) return "—";
  const s = Math.round(seconds);
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
};

/** Suma segundos a un timestamp local "AAAA-MM-DDTHH:MM:SS" y devuelve solo la hora. */
export const clockAt = (startTs: string, offset: number) => {
  const date = new Date(startTs);
  date.setSeconds(date.getSeconds() + Math.floor(offset));
  return date.toTimeString().slice(0, 8);
};
