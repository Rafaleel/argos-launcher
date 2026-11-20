import { useCallback, useEffect, useState } from "react";
import { BarChart3, Cpu, Library as LibraryIcon, Settings as SettingsIcon, Trophy, X } from "lucide-react";
import { api, DolphinInfo, Game } from "./api";
import { Notify, splitTitle } from "./ui";
import { Library } from "./pages/Library";
import { GamePage } from "./pages/GamePage";
import { Stats } from "./pages/Stats";
import { Emulators } from "./pages/Emulators";
import { Achievements } from "./pages/Achievements";
import { Settings } from "./pages/Settings";

type Route = { page: "library" | "game" | "stats" | "emulators" | "achievements" | "settings"; id?: number };

function parse(hash: string): Route {
  const [, page, id] = hash.replace(/^#/, "").split("/");
  if (page === "game" && Number(id)) return { page: "game", id: Number(id) };
  if (page === "stats" || page === "emulators" || page === "achievements" || page === "settings") return { page };
  return { page: "library" };
}

function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(location.hash));
  useEffect(() => {
    const on = () => { setRoute(parse(location.hash)); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

/** The eye of Argos, drawn small. */
function Mark() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
      <circle cx="12" cy="12" r="3.2" fill="currentColor" stroke="none" />
    </svg>
  );
}

const NAV = [
  { page: "library", label: "Biblioteca", icon: LibraryIcon, href: "#/" },
  { page: "stats", label: "Estatísticas", icon: BarChart3, href: "#/stats" },
  { page: "achievements", label: "Conquistas", icon: Trophy, href: "#/achievements" },
  { page: "emulators", label: "Emuladores", icon: Cpu, href: "#/emulators" },
  { page: "settings", label: "Configurações", icon: SettingsIcon, href: "#/settings" },
] as const;

export type Ctx = {
  games: Game[];
  loaded: boolean;
  info: DolphinInfo | null;
  notify: Notify;
  refresh: () => Promise<void>;
  play: (g: Game) => void;
};

export default function App() {
  const route = useRoute();
  const [games, setGames] = useState<Game[] | null>(null);
  const [info, setInfo] = useState<DolphinInfo | null>(null);
  const [toast, setToast] = useState<{ text: string; error: boolean } | null>(null);

  const notify: Notify = useCallback((text, error = false) => setToast({ text, error }), []);
  const refresh = useCallback(async () => {
    api.dolphinInfo().then(setInfo).catch(() => undefined); // the library must load even if this fails
    setGames(await api.games());
  }, []);

  // The desktop app starts the backend together with the window: keep trying for a while before giving up.
  useEffect(() => {
    let stop = false;
    (async () => {
      for (let i = 0; !stop; i++) {
        try { await refresh(); return; } catch (e) {
          if (i >= 40) { notify(`Não consegui falar com o backend do Argos: ${e instanceof Error ? e.message : e}`, true); return; }
          await new Promise((r) => setTimeout(r, 500));
        }
      }
    })();
    return () => { stop = true; };
  }, [refresh, notify]);

  useEffect(() => {
    if (!toast || toast.error) return;
    const id = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(id);
  }, [toast]);

  // While a game is open, poll so "jogando agora" and the time clear by themselves.
  const playing = games?.find((g) => g.playing);
  useEffect(() => {
    if (!playing) return;
    let busy = false;
    const id = setInterval(() => {
      if (busy) return;
      busy = true;
      refresh().catch(() => undefined).finally(() => { busy = false; });
    }, 5000);
    return () => clearInterval(id);
  }, [playing?.id, refresh]);

  const play = (g: Game) =>
    api.play(g.id).then(() => { notify(`Abrindo ${splitTitle(g.title).name}…`); return refresh(); }).catch((e) => notify(e.message, true));

  const ctx: Ctx = { games: games ?? [], loaded: games !== null, info, notify, refresh, play };
  const current = route.page === "game" ? "library" : route.page;

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand"><Mark /> Argos</div>
        <nav aria-label="Principal">
          {NAV.map(({ page, label, icon: Icon, href }) => (
            <a key={page} className="nav" href={href} aria-current={current === page ? "page" : undefined}>
              <Icon /> {label}
            </a>
          ))}
        </nav>
        {playing && (
          <a className="side-foot" href={`#/game/${playing.id}`} style={{ color: "inherit", textDecoration: "none" }}>
            <div className="eyebrow"><span className="pulse" />Jogando agora</div>
            <div className="title">{splitTitle(playing.title).name}</div>
          </a>
        )}
      </aside>

      <main className="page">
        {games === null && <p className="muted">Conectando…</p>}
        {games !== null && route.page === "library" && <Library {...ctx} />}
        {route.page === "game" && route.id !== undefined && <GamePage key={route.id} id={route.id} {...ctx} />}
        {route.page === "stats" && <Stats games={ctx.games} />}
        {route.page === "achievements" && <Achievements {...ctx} />}
        {route.page === "emulators" && <Emulators {...ctx} />}
        {route.page === "settings" && <Settings {...ctx} />}
      </main>

      {toast && (
        <div className={`toast ${toast.error ? "err" : ""}`} role={toast.error ? "alert" : "status"}>
          <span>{toast.text}</span>
          <button className="btn ghost icon" aria-label="Fechar aviso" onClick={() => setToast(null)}><X /></button>
        </div>
      )}
    </div>
  );
}
