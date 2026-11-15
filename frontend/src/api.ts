export type Game = {
  id: number;
  title: string;
  platform: string | null;
  identified: boolean;
  has_emulator: boolean;
};
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
  play: (id: number) => call<{ pid: number }>(`/games/${id}/play`, "POST"),
};
