import { useCallback, useEffect, useState } from "react";
import { Activity, Archive, Moon, Sun, Wrench, X } from "lucide-react";
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

const NAV = [
  { name: "Acervo", href: "#/", icon: Archive },
  { name: "Atividade", href: "#/stats", icon: Activity },
  { name: "Oficina", href: "#/emulators", icon: Wrench },
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
  const [light, setLight] = useState(() => document.documentElement.dataset.theme === "light");
  const toggleTheme = () => {
    const next = light ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("argos.theme", next); } catch { /* session only */ }
    setLight(!light);
  };
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
          // a first start may need to install dependencies: warn once, keep trying
          if (i === 40) notify(`O backend do Argos ainda não respondeu (${e instanceof Error ? e.message : e}). Continuo tentando…`, true);
          await new Promise((r) => setTimeout(r, i < 40 ? 500 : 2000));
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
  const activity = route.page === "stats" || route.page === "achievements";
  const workshop = route.page === "emulators" || route.page === "settings";
  const current = activity ? "Atividade" : workshop ? "Oficina" : "Acervo";
  const sections = activity
    ? [["stats", "Diário e estatísticas"], ["achievements", "Conquistas"]]
    : [["emulators", "Emuladores"], ["settings", "Pastas e arquivos"]];

  return (
    <div className="shell">
      <header className="masthead">
        <div className="mast-inner">
          <a className="wordmark" href="#/" aria-label="Argos · Acervo"><img src="/mark.svg" alt="" />Argos</a>
          <nav className="main-nav" aria-label="Principal">
            {NAV.map(({ name, href, icon: Icon }) => (
              <a key={name} href={href} aria-current={current === name ? "page" : undefined}><Icon />{name}</a>
            ))}
          </nav>
          <div className="mast-tools">
            {playing && <a className="live-link" href={`#/game/${playing.id}`} title={splitTitle(playing.title).name}><span className="pulse" />Jogando agora</a>}
            <button className="theme-switch" onClick={toggleTheme} aria-label={light ? "Ativar tema escuro" : "Ativar tema claro"} title={light ? "Ativar tema escuro" : "Ativar tema claro"}>
              {light ? <Moon /> : <Sun />}
            </button>
          </div>
        </div>
      </header>
      <main className="page">
        {(activity || workshop) && (
          <div className="section-mast">
            <h1>{current}</h1>
            <nav aria-label={current}>{sections.map(([page, label]) => (
              <a key={page} href={`#/${page}`} aria-current={route.page === page ? "page" : undefined}>{label}</a>
            ))}</nav>
          </div>
        )}
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
