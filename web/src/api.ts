// Tipos y llamadas a la api de Sentinel (todas bajo /api).

export interface DaySummary {
  day: string;
  clips: number;
  person_clips: number;
  person_seconds: number;
  faces: number;
  pending: number;
}

export interface Clip {
  id: number;
  path: string;
  day: string;
  start_ts: string;
  status: "pending" | "done" | "error";
  error: string | null;
  duration: number | null;
  fps: number | null;
  width: number | null;
  height: number | null;
  max_persons: number;
  person_seconds: number;
  first_person: number | null;
  face_count: number;
  processed_at: string | null;
}

export interface Box {
  t: number;
  conf: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface Face {
  id: number;
  clip_id: number;
  t: number;
  conf: number;
  ts: string;
}

export interface ClipDetail extends Clip {
  detections: Box[];
  faces: (Face & Box)[];
}

export interface HourActivity {
  hour: number;
  clips: number;
  person_clips: number;
  person_seconds: number;
  faces: number;
}

export interface Status {
  worker: boolean;
  current: string | null;
  pending: number;
  done: number;
  error: number;
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

export const api = {
  status: () => get<Status>("/status"),
  days: () => get<DaySummary[]>("/days"),
  clips: (day: string) => get<Clip[]>(`/days/${day}/clips`),
  timeline: (day: string) => get<HourActivity[]>(`/days/${day}/timeline`),
  faces: (day: string) => get<Face[]>(`/days/${day}/faces`),
  clip: (id: number) => get<ClipDetail>(`/clips/${id}`),
};

export const videoUrl = (id: number) => `/api/clips/${id}/video`;
// El sufijo ?v= evita ver una miniatura vieja cuando un clip se reprocesa.
export const thumbUrl = (clip: Clip) => `/api/clips/${clip.id}/thumb?v=${clip.processed_at ?? ""}`;
export const faceUrl = (id: number) => `/api/faces/${id}/image`;
