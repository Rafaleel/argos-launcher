export type Game = {
  id: number;
  title: string;
  platform: string | null;
  identified: boolean;
  has_emulator: boolean;
  playing: boolean;
  seconds_played: number;
};
export type PlatformTime = { platform: string | null; seconds: number };
export type GameTime = { game_id: number; title: string; platform: string | null; seconds: number; sessions: number; last_played: string | null };
export type Period = { period: string; seconds: number };
export type By = "day" | "week" | "month";

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  const min = Math.floor(seconds / 60);
  if (min < 60) return `${min} min`;
  return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")} min`;
}
export type Settings = { rom_dirs: string[]; dat_dirs: string[] };
export type Emulator = { platform: string; executable: string; args: string[] };
export type ScanResult = {
  files_hashed: number;
  files_cached: number;
  files_removed: number;
  games: number;
  errors: string[];
};

async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(typeof detail?.detail === "string" ? detail.detail : `Erro ${res.status}`);
  }
  return res.json();
}

export const api = {
  settings: () => call<Settings>("/settings"),
  saveSettings: (s: Settings) => call<Settings>("/settings", "PUT", s),
  scan: () => call<ScanResult>("/scan", "POST"),
  games: () => call<Game[]>("/games"),
  platforms: () => call<string[]>("/platforms"),
  emulators: () => call<Emulator[]>("/emulators"),
  saveEmulator: (e: Emulator) => call<Emulator>("/emulators", "PUT", e),
  statsGames: () => call<GameTime[]>("/stats/games"),
  statsPlatforms: () => call<PlatformTime[]>("/stats/platforms"),
  statsPeriods: (by: By) => call<Period[]>(`/stats/periods?by=${by}`),
  play: (id: number) => call<{ pid: number; session_id: number }>(`/games/${id}/play`, "POST"),
};
