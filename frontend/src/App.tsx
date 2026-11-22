import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Archive, BarChart3, Clock3, Cpu, FolderOpen, KeyRound, LucideIcon, Moon, Sun, Trophy, Wrench, X } from "lucide-react";
import { api, DolphinInfo, formatDuration, Game } from "./api";
import { collectEditions } from "./collection";
import { Notify, splitTitle } from "./ui";
import { Library } from "./pages/Library";
import { GamePage } from "./pages/GamePage";
import { Stats } from "./pages/Stats";
import { Emulators } from "./pages/Emulators";
import { Achievements } from "./pages/Achievements";
import { Settings } from "./pages/Settings";
import { Accounts } from "./pages/Accounts";

type Route = { page: "library" | "game" | "stats" | "emulators" | "achievements" | "settings" | "accounts"; id?: number };

function parse(hash: string): Route {
  const [, page, id] = hash.replace(/^#/, "").split("/");
  if (page === "game" && Number(id)) return { page: "game", id: Number(id) };
  if (page === "stats" || page === "emulators" || page === "achievements" || page === "settings" || page === "accounts") return { page };
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

  // The backend syncs the achievements right after a game closes: look again a few times so the new counts show up.
  const wasPlaying = useRef(false);
  useEffect(() => {
    const ended = wasPlaying.current && !playing;
    wasPlaying.current = !!playing;
    if (!ended) return;
    const timers = [3000, 10000, 30000].map((ms) => setTimeout(() => refresh().catch(() => undefined), ms));
    return () => timers.forEach(clearTimeout);
  }, [playing, refresh]);

  // Global keyboard shortcuts: 1/2/3 switch top sections, "/" focuses the visible search box.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
      if (document.querySelector(".select-list")) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.key === "1") { e.preventDefault(); location.hash = "#/"; }
      else if (e.key === "2") { e.preventDefault(); location.hash = "#/stats"; }
      else if (e.key === "3") { e.preventDefault(); location.hash = "#/emulators"; }
      else if (e.key === "/") {
        const input = document.querySelector<HTMLInputElement>("[data-search-input], .search input");
        if (input) { e.preventDefault(); input.focus(); input.select(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const play = (g: Game) =>
    api.play(g.id).then(() => { notify(`Abrindo ${splitTitle(g.title).name}…`); return refresh(); }).catch((e) => notify(e.message, true));

  const ctx: Ctx = { games: games ?? [], loaded: games !== null, info, notify, refresh, play };
  const activity = route.page === "stats" || route.page === "achievements";
  const workshop = route.page === "emulators" || route.page === "settings" || route.page === "accounts";
  const current = activity ? "Atividade" : workshop ? "Oficina" : "Acervo";
  const sectionSub = activity
    ? "Diário de sessões, ritmo de jogo e progresso de conquistas."
    : "Emuladores, pastas do acervo e contas locais.";
  const sections: [Route["page"], string, LucideIcon][] = activity
    ? [
      ["stats", "Diário e estatísticas", BarChart3],
      ["achievements", "Conquistas", Trophy],
    ]
    : [
      ["emulators", "Emuladores", Cpu],
      ["settings", "Pastas e DATs", FolderOpen],
      ["accounts", "RetroAchievements", KeyRound],
    ];

  const editions = collectEditions(ctx.games);
  const totalSeconds = ctx.games.reduce((sum, g) => sum + g.seconds_played, 0);
  const totalEarned = editions.reduce((sum, discs) => {
    const newest = discs.map((d) => d.achievements).filter((a) => a !== null)
      .sort((a, b) => (b!.synced_at ?? "").localeCompare(a!.synced_at ?? ""))[0];
    return sum + (newest?.earned ?? 0);
  }, 0);
  const identifiedPlatforms = [...new Set(ctx.games.map((g) => g.platform).filter((p): p is string => p !== null))];
  const readyPlatforms = identifiedPlatforms.filter((p) => ctx.games.some((g) => g.platform === p && g.has_emulator)).length;
  const workshopNeedsAttention = ctx.loaded && ((identifiedPlatforms.length > 0 && readyPlatforms < identifiedPlatforms.length) || !!info?.running);

  return (
    <div className="shell">
      <header className="masthead">
        <div className="mast-inner">
          <a className="wordmark" href="#/" aria-label="Argos · Acervo"><img src="/mark.svg" alt="" />Argos</a>
          <nav className="main-nav" aria-label="Principal">
            {NAV.map(({ name, href, icon: Icon }) => (
              <a key={name} href={href} aria-current={current === name ? "page" : undefined}>
                <Icon />{name}
                {name === "Oficina" && workshopNeedsAttention && (
                  <span className="nav-alert-dot" role="img" aria-label="Requer atenção" title={info?.running ? "Dolphin aberto" : "Há plataformas sem emulador"} />
                )}
              </a>
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
            <div className="mast-top">
              <div className="mast-heading">
                <div className="kicker"><span className="signal" />{current}</div>
                <h1>{current}</h1>
                <p className="mast-sub">{sectionSub}</p>
              </div>
              {ctx.loaded && (
                <div className="mast-pills" aria-label="Resumo rápido">
                  {activity ? (
                    <>
                      <span className="mast-pill"><Clock3 size={14} aria-hidden="true" /><b className="num">{formatDuration(totalSeconds)}</b> registrados</span>
                      {totalEarned > 0 && <span className="mast-pill gold"><Trophy size={14} aria-hidden="true" /><b className="num">{totalEarned}</b> conquistas</span>}
                    </>
                  ) : (
                    <>
                      {identifiedPlatforms.length > 0 && (
                        <span className={`mast-pill ${readyPlatforms === identifiedPlatforms.length ? "gold" : "warn"}`}>
                          <Cpu size={14} aria-hidden="true" /><b className="num">{readyPlatforms}/{identifiedPlatforms.length}</b> plataformas prontas
                        </span>
                      )}
                      {info?.running && <span className="mast-pill warn"><span className="status-dot off" />Dolphin aberto</span>}
                    </>
                  )}
                </div>
              )}
            </div>
            <nav className="mast-tabs" aria-label={current}>{sections.map(([page, label, Icon]) => (
              <a key={page} href={`#/${page}`} aria-current={route.page === page ? "page" : undefined}>
                <Icon size={15} aria-hidden="true" />{label}
              </a>
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
        {route.page === "accounts" && <Accounts {...ctx} />}
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
