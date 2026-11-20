import { useMemo, useState } from "react";
import { FolderPlus, LayoutGrid, List, Play, Search } from "lucide-react";
import type { Ctx } from "../App";
import { formatDuration, Game } from "../api";
import { Cover, platformName, splitTitle } from "../ui";

type View = "grid" | "list";

function savedView(): View {
  try {
    return localStorage.getItem("argos.view") === "list" ? "list" : "grid";
  } catch {
    return "grid";
  }
}

const open = (g: Game) => { location.hash = `#/game/${g.id}`; };

function achievementsShort(g: Game) {
  const a = g.achievements;
  return a && a.total > 0 ? `${a.earned}/${a.total}` : "—";
}

export function Library({ games, loaded, play }: Ctx) {
  const [view, setView] = useState<View>(savedView);
  const [query, setQuery] = useState("");
  // "?" = files no DAT recognised (texture packs, zips): kept out of the shelf unless asked for
  const [platform, setPlatform] = useState<string | null>(null);

  const setAndSave = (v: View) => {
    setView(v);
    try { localStorage.setItem("argos.view", v); } catch { /* private mode: just not remembered */ }
  };

  const platforms = useMemo(() => [...new Set(games.map((g) => g.platform).filter((p): p is string => p !== null))], [games]);
  const unknown = games.filter((g) => !g.identified).length;
  const shown = games.filter((g) =>
    (platform === "?" ? !g.identified : g.identified && (platform === null || g.platform === platform))
    && g.title.toLowerCase().includes(query.trim().toLowerCase()));
  const canPlay = (g: Game) => g.identified && g.has_emulator && !g.playing;

  if (loaded && games.length === 0) {
    return (
      <>
        <div className="page-head"><div><h1>Biblioteca</h1></div></div>
        <div className="empty">
          <FolderPlus />
          <h2>Sua estante está vazia</h2>
          <p>Escolha a pasta onde ficam seus jogos. O Argos identifica cada um e acha o emulador instalado.</p>
          <a className="btn primary" href="#/settings">Escolher pasta de jogos</a>
        </div>
      </>
    );
  }

  if (loaded && unknown === games.length && platform !== "?") {
    return (
      <>
        <div className="page-head"><div><h1>Biblioteca</h1></div></div>
        <div className="empty">
          <FolderPlus />
          <h2>Nenhum jogo reconhecido ainda</h2>
          <p>Encontrei {unknown} {unknown === 1 ? "arquivo" : "arquivos"}, mas sem os DATs do No-Intro/Redump não sei que jogos são.</p>
          <div className="row" style={{ justifyContent: "center" }}>
            <a className="btn primary" href="#/settings">Adicionar pasta de DATs</a>
            <button className="btn ghost" onClick={() => setPlatform("?")}>Ver os arquivos</button>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Biblioteca</h1>
          <p className="num">{games.length - unknown} {games.length - unknown === 1 ? "jogo" : "jogos"}</p>
        </div>
      </div>

      <div className="toolbar">
        <div className="search">
          <Search />
          <input aria-label="Buscar jogo" placeholder="Buscar" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        {(platforms.length > 1 || unknown > 0) && (
          <div className="chips" role="group" aria-label="Plataforma">
            <button className="chip" aria-pressed={platform === null} onClick={() => setPlatform(null)}>Todas</button>
            {platforms.map((p) => (
              <button key={p} className="chip" aria-pressed={platform === p} onClick={() => setPlatform(p)}>{platformName(p)}</button>
            ))}
            {unknown > 0 && (
              <button className="chip" aria-pressed={platform === "?"} onClick={() => setPlatform("?")}>Não identificados · {unknown}</button>
            )}
          </div>
        )}
        <div className="spacer" />
        <div className="seg" role="group" aria-label="Visualização">
          <button aria-pressed={view === "grid"} onClick={() => setAndSave("grid")}><LayoutGrid /> Grade</button>
          <button aria-pressed={view === "list"} onClick={() => setAndSave("list")}><List /> Lista</button>
        </div>
      </div>

      {shown.length === 0 && <p className="muted">Nenhum jogo com esse filtro.</p>}

      {view === "grid" ? (
        <div className="shelf-grid">
          {shown.map((g, i) => (
            <div key={g.id} className="tile" style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}>
              <div className="art">
                <Cover game={g} />
                <button aria-label={`Abrir ${splitTitle(g.title).name}`} onClick={() => open(g)}
                  style={{ position: "absolute", inset: 0, border: 0, padding: 0, background: "transparent", cursor: "pointer" }} />
                {g.playing && <span className="badge-live">Jogando</span>}
                {canPlay(g) && (
                  <button className="play-fab" aria-label={`Jogar ${splitTitle(g.title).name}`} onClick={() => play(g)}><Play /></button>
                )}
              </div>
              <div onClick={() => open(g)} style={{ cursor: "pointer" }}>
                <div className="name">{splitTitle(g.title).name}</div>
                <div className="meta">
                  <span>{platformName(g.platform)}</span>
                  <span className="num">{g.seconds_played ? formatDuration(g.seconds_played) : "Nunca jogado"}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="shelf-list">
          <div className="line line-head eyebrow">
            <span /><span>Jogo</span><span>Plataforma</span><span>Tempo</span><span>Conquistas</span><span />
          </div>
          {shown.map((g) => (
            <div key={g.id} className="line" onClick={() => open(g)}>
              <div className="thumb"><Cover game={g} /></div>
              <div>
                <div className="name">{splitTitle(g.title).name}</div>
                <div className="muted" style={{ fontSize: 12 }}>
                  {g.playing ? <><span className="pulse" />Jogando agora</> : splitTitle(g.title).tags}
                </div>
              </div>
              <span className="soft">{platformName(g.platform)}</span>
              <span className="num soft">{g.seconds_played ? formatDuration(g.seconds_played) : "—"}</span>
              <span className="num soft">{achievementsShort(g)}</span>
              <button className="btn" disabled={!canPlay(g)} onClick={(e) => { e.stopPropagation(); play(g); }}
                title={!g.identified ? "Jogo não identificado" : !g.has_emulator ? "Nenhum emulador para esta plataforma" : ""}>
                <Play /> Jogar
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
