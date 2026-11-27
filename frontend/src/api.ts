export type ProgressBrief = {
  mean: number;
  lower: number;
  upper: number;
  margin: number;
  scenario: string;
};
export type ScenarioProgress = {
  scenario: string;
  mean: number;
  lower: number;
  upper: number;
  margin: number;
  furthest: number | null;
  total: number | null;
  win_reached: boolean;
  resets: number;
  sources: string[];
};
export type RemainingHours = { mean: number; min: number; max: number };
export type GameProgress =
  | { available: false; ttb_hours: number | null; pace_pct_per_hour: null; remaining_hours: null }
  | {
      available: true;
      mean: number;
      lower: number;
      upper: number;
      margin: number;
      scenario: string;
      scenarios: ScenarioProgress[];
      sources: string[];
      mode: "milestones" | "generic";
      ttb_hours: number | null;
      pace_pct_per_hour: number | null;
      remaining_hours: RemainingHours | null;
      updated_at: string;
    };
export type InsightGame = {
  game_id: number;
  title: string;
  platform: string | null;
  seconds: number;
  sessions: number;
  last_played: string | null;
  progress: ProgressBrief | null;
  pace_pct_per_hour: number | null;
  remaining_hours: RemainingHours | null;
  days_idle?: number;
};
export type ProgressInsights = {
  abandoned_days: number;
  in_progress: InsightGame[];
  abandoned: InsightGame[];
};

export type Game = {
  id: number;
  title: string;
  platform: string | null;
  identified: boolean;
  has_emulator: boolean;
  playing: boolean;
  seconds_played: number;
  dolphin: boolean;
  ra_id: number | null;
  achievements: AchievementSummary | null;
  presence: { message: string; at: string | null } | null; // last RetroAchievements rich presence line
  progress: ProgressBrief | null;
};
export type Milestones =
  | { supported: false }
  | { supported: true; total: number; reached: number; items: { name: string; reached: boolean }[]; read_at: string | null; problem: string | null };

export type RaAchievement = { id: number; title: string; description: string; points: number; type: string; earned: boolean; at: string | null; hardcore: boolean };

export type AchievementSummary = {
  title: string;
  total: number;
  earned: number;
  earned_hardcore: number;
  points_earned: number;
  points_total: number;
  percent: number | null;
  synced_at: string | null;
};
export type RaSettings = { user: string; has_key: boolean };
export type RaSyncResult = { game_id: number; title: string; ok: boolean; message: string };
export type PlatformTime = { platform: string | null; seconds: number };
export type GameTime = { game_id: number; title: string; platform: string | null; seconds: number; sessions: number; last_played: string | null };
export type JournalDay = { day: string; games: GameTime[] };
export type JournalPage = { days: JournalDay[]; next_before: string | null };
export type Period = { period: string; seconds: number };
export type By = "day" | "week" | "month";

export type VideoSettings = {
  backend?: "Vulkan" | "OGL";
  gpu?: "nvidia";
  internal_resolution?: number;
  anisotropy?: number;
  vsync?: boolean;
  hires_textures?: boolean;
  prefetch_textures?: boolean;
  render_to_main?: boolean;
  background_input?: boolean;
  keep_on_top?: boolean;
};
export type Controller = { name: string; device: string; source: "sdl" | "kernel" };
export type DolphinInfo = {
  detected: boolean;
  flatpak: boolean | null;
  running: boolean;
  gpus: string[];
  nvidia_ready: boolean | null;
  controllers: Controller[];
  seven_zip: boolean;
  pad_device: string | null;
  presets: string[];
};
export type TexturePack = { installed: boolean; folder: string | null; files: number; bytes: number };
export type Profile = {
  settings: VideoSettings;
  defaults: VideoSettings;
  effective: VideoSettings;
  game_code: string | null;
  textures: TexturePack | null;
};
export type PackJob = { state: "idle" | "running" | "done" | "error"; message: string; game_id: string | null };

export function formatBytes(bytes: number): string {
  return bytes >= 2 ** 30 ? `${(bytes / 2 ** 30).toFixed(1)} GB` : `${Math.round(bytes / 2 ** 20)} MB`;
}

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
  emulators_configured: { platform: string; name: string }[];
};
export type EmulatorOption = { name: string; platforms: string[]; executable: string; args: string[] };
export type DolphinRa = { enabled: boolean; user: string; logged_in: boolean; hardcore: boolean };

export const inDesktop = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
// Served over http (the browser, or `tauri dev` loading Vite): same origin through Vite's proxy.
// The built desktop app serves the UI from tauri://localhost and calls the backend port directly.
const BASE = location.protocol.startsWith("http") ? "/api" : "http://127.0.0.1:8765/api";
export const coverUrl = (id: number) => `${BASE}/games/${id}/cover`;

async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    const d = detail?.detail;
    // validation errors come as a list of {loc, msg}; show the first message
    throw new Error(typeof d === "string" ? d : Array.isArray(d) && d[0]?.msg ? String(d[0].msg) : `Erro ${res.status}`);
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
  journal: (before: string | null) => call<JournalPage>(before ? `/stats/journal?before=${encodeURIComponent(before)}` : "/stats/journal"),
  statsGames: () => call<GameTime[]>("/stats/games"),
  statsPlatforms: () => call<PlatformTime[]>("/stats/platforms"),
  statsPeriods: (by: By) => call<Period[]>(`/stats/periods?by=${by}`),
  dolphinInfo: () => call<DolphinInfo>("/dolphin/info"),
  dolphinDefaults: () => call<VideoSettings>("/dolphin/defaults"),
  saveDolphinDefaults: (v: VideoSettings) => call<VideoSettings>("/dolphin/defaults", "PUT", v),
  profile: (id: number) => call<Profile>(`/games/${id}/profile`),
  saveProfile: (id: number, v: VideoSettings) => call<VideoSettings>(`/games/${id}/profile`, "PUT", v),
  installTextures: (id: number, archive: string) => call<{ started: boolean }>(`/games/${id}/textures`, "POST", { archive }),
  removeTextures: (id: number) => call<{ removed: boolean }>(`/games/${id}/textures`, "DELETE"),
  packJob: () => call<PackJob>("/dolphin/textures/job"),
  saveControls: (preset: string, device: string | null) => call<{ device: string | null }>("/dolphin/controls", "PUT", { preset, device }),
  raSettings: () => call<RaSettings>("/ra/settings"),
  saveRaSettings: (user: string, key: string | null) => call<RaSettings>("/ra/settings", "PUT", key === null ? { user } : { user, key }),
  gameRa: (id: number) => call<{ ra_id: number | null; summary: AchievementSummary | null }>(`/games/${id}/ra`),
  achievements: (id: number) => call<{ ra_id: number | null; items: RaAchievement[] }>(`/games/${id}/achievements`),
  milestones: (id: number) => call<Milestones>(`/games/${id}/milestones`),
  saveGameRa: (id: number, ra: string) => call<{ ra_id: number | null }>(`/games/${id}/ra`, "PUT", { ra }),
  syncGameRa: (id: number) => call<AchievementSummary>(`/games/${id}/ra/sync`, "POST"),
  syncAllRa: () => call<RaSyncResult[]>("/ra/sync", "POST"),
  detectGameRa: (id: number) => call<{ found: boolean; ra_id: number | null; hash: string }>(`/games/${id}/ra/detect`, "POST"),
  detectAllRa: () => call<RaSyncResult[]>("/ra/detect", "POST"),
  detectedEmulators: () => call<Record<string, EmulatorOption[]>>("/emulators/detected"),
  dolphinRa: () => call<DolphinRa>("/dolphin/achievements"),
  dolphinRaLogin: (user: string, password: string) => call<DolphinRa>("/dolphin/achievements/login", "POST", { user, password }),
  dolphinRaLogout: () => call<DolphinRa>("/dolphin/achievements/login", "DELETE"),
  gameProgress: (id: number) => call<GameProgress>(`/games/${id}/progress`),
  saveProgressConfig: (id: number, ttb_hours: number | null) =>
    call<GameProgress>(`/games/${id}/progress/config`, "PUT", { ttb_hours }),
  recomputeProgress: (id: number) => call<GameProgress>(`/games/${id}/progress/recompute`, "POST"),
  statsInsights: (abandonedDays = 30) => call<ProgressInsights>(`/stats/insights?abandoned_days=${abandonedDays}`),
  play: (id: number) => call<{ pid: number; session_id: number }>(`/games/${id}/play`, "POST"),
};
