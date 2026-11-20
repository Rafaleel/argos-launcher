import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, ArrowUpRight, ChevronLeft, ChevronRight, Clock3, Disc3, Eye, FolderPlus, Gamepad2, LayoutGrid, List, Play, Search } from "lucide-react";
import type { Ctx } from "../App";
import { api, formatDuration, Game, GameTime } from "../api";
import { collectEditions, editionTitle } from "../collection";
import { GameMedia } from "../GameMedia";
import { Cover, localDate, platformName, splitTitle } from "../ui";

type View = "grid" | "list";

function savedView(): View {
  try { return localStorage.getItem("argos.view") === "list" ? "list" : "grid"; }
  catch { return "grid"; }
}

function SpotlightTitle({ name }: { name: string }) {
  const heading = useRef<HTMLHeadingElement>(null);
  const text = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const box = heading.current!;
    const label = text.current!;
    function fit() {
      label.style.fontSize = "";
      box.removeAttribute("tabindex");
      let low = 18;
      let high = Math.floor(parseFloat(getComputedStyle(box).fontSize));
      const fits = () => label.offsetHeight <= box.clientHeight && label.scrollWidth <= box.clientWidth;
      if (fits()) return;
      // Measure the actual line breaks, including differences in glyph width and font loading.
      while (low < high) {
        const size = Math.ceil((low + high) / 2);
        label.style.fontSize = size + "px";
        if (fits()) low = size;
        else high = size - 1;
      }
      label.style.fontSize = low + "px";
      if (!fits()) box.tabIndex = 0;
    }
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(box);
    document.fonts.addEventListener("loadingdone", fit);
    return () => {
      observer.disconnect();
      document.fonts.removeEventListener("loadingdone", fit);
    };
  }, [name]);
  return <h1 ref={heading} className="spot-title" aria-live="polite" title={name}><span ref={text}>{name}</span></h1>;
}

function Spotlight({ discs, history, isRecent, index, count, browse, play }: {
  discs: Game[]; history: Map<number, GameTime>; isRecent: boolean; index: number; count: number;
  browse: (step: number) => void; play: Ctx["play"];
}) {
  const game = discs.find(d => d.playing) ?? discs[0];
  const multi = discs.length > 1;
  const title = splitTitle(multi ? editionTitle(game.title) : game.title);
  const latest = discs.map(d => history.get(d.id)?.last_played).filter((date): date is string => !!date).sort().at(-1);
  const seconds = discs.reduce((sum, d) => sum + d.seconds_played, 0);
  const playable = !multi && game.identified && game.has_emulator && !game.playing;
  return (
    <section className="spotlight" aria-label="Jogo em destaque" data-browse>
      <div className="spot-copy">
        <div className="spot-top">
          <div className="kicker"><span className="signal" />{game.playing ? "Jogando agora" : isRecent ? "Última sessão" : "Em destaque"}</div>
          {count > 1 && <div className="browse-controls" role="group" aria-label="Folhear acervo">
            <button onClick={() => browse(-1)} aria-label="Título anterior"><ChevronLeft /></button>
            <span>{index + 1} / {count}</span>
            <button onClick={() => browse(1)} aria-label="Próximo título"><ChevronRight /></button>
          </div>}
        </div>
        <SpotlightTitle name={title.name} />
        <div className="spot-meta">
          <span><Gamepad2 />{platformName(game.platform)}</span>
          {multi && <span><Disc3 />{discs.length} discos</span>}
          {game.identified && <span><Clock3 />{latest ? `${localDate(latest)} · ${formatDuration(seconds)} no total` : seconds ? formatDuration(seconds) : "Ainda não jogado"}</span>}
        </div>
        <div className="spot-actions">
          {playable && <button className="btn primary big" onClick={() => play(game)}><Play fill="currentColor" />Jogar</button>}
          <a className={playable ? "text-link" : "btn primary big"} href={`#/game/${game.id}`}>
            {multi ? "Escolher disco" : "Ver ficha"} <ArrowUpRight />
          </a>
        </div>
      </div>
      <GameMedia game={game} />
    </section>
  );
}

export function Library({ games, play }: Ctx) {
  const [selection, setSelection] = useState<number | null>(null);
  const shelf = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View>(savedView);
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState<string | null>(null);
  const [history, setHistory] = useState<GameTime[]>([]);
  useEffect(() => {
    let active = true;
    api.statsGames().then(rows => { if (active) setHistory(rows); }).catch(() => undefined);
    return () => { active = false; };
  }, [games]);
  const editions = useMemo(() => collectEditions(games), [games]);
  const identified = editions.filter(([g]) => g.identified);
  const unknown = games.filter(g => !g.identified).length;
  const platforms = [...new Set(identified.map(([g]) => g.platform).filter((p): p is string => p !== null))];
  const lastPlayed = new Map(history.map(row => [row.game_id, row]));
  const recent = games.filter(g => g.identified && lastPlayed.get(g.id)?.last_played)
    .sort((a, b) => lastPlayed.get(b.id)!.last_played!.localeCompare(lastPlayed.get(a.id)!.last_played!))[0];
  const initial = games.find(g => g.identified && g.playing) ?? recent;
  const needle = query.trim().toLocaleLowerCase();
  const shown = editions.filter(discs => {
    const [g] = discs;
    return (platform === "?" ? !g.identified : g.identified && (platform === null || platform === g.platform))
      && discs.some(d => (d.title + " " + splitTitle(d.title).name).toLocaleLowerCase().includes(needle));
  });
  const selected = shown.find(group => group[0].id === selection)
    ?? shown.find(group => group.some(g => g.id === initial?.id)) ?? shown[0];
  const index = shown.indexOf(selected);
  function browse(step: number, focusShelf = false) {
    if (shown.length < 2) return;
    const id = shown[(index + step + shown.length) % shown.length][0].id;
    setSelection(id);
    if (focusShelf) shelf.current?.querySelector<HTMLButtonElement>(`[data-edition="${id}"]`)?.focus();
  }
  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const target = event.target;
      if (!(target instanceof Element) || (target !== document.body && !target.closest("[data-browse]"))) return;
      if (shown.length < 2) return;
      event.preventDefault();
      browse(event.key === "ArrowRight" ? 1 : -1, !!target.closest("[data-edition]"));
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  });
  function changeView(next: View) {
    setView(next);
    try { localStorage.setItem("argos.view", next); } catch { /* session only */ }
  }

  if (!identified.length && platform !== "?") {
    return (
      <section className="empty-start">
        <div><div className="kicker"><span className="signal" />Acervo</div>
          <h1>{unknown ? "Arquivos por identificar" : "Sua primeira estante"}</h1>
          <p>{unknown ? `O Argos encontrou ${unknown} ${unknown === 1 ? "arquivo" : "arquivos"}. Adicione os DATs do No-Intro ou Redump para identificar os jogos compatíveis.` : "Escolha a pasta de jogos e os arquivos DAT para montar seu acervo."}</p>
          <div className="spot-actions">
            <a className="btn primary big" href="#/settings"><FolderPlus />{unknown ? "Adicionar DATs" : "Escolher pasta"}</a>
            {unknown > 0 && <button className="text-link" onClick={() => setPlatform("?")}>Ver arquivos <ArrowRight /></button>}
          </div>
        </div>
        <div className="empty-art" aria-hidden="true"><span /></div>
      </section>
    );
  }

  return (
    <>
      {selected && <Spotlight discs={selected} history={lastPlayed} index={index} count={shown.length}
        isRecent={selected.some(g => g.id === recent?.id)} browse={browse} play={play} />}
      <section className="collection" aria-label="Meu acervo">
        <div className="collection-head">
          <div className="collection-title"><h2>Meu acervo</h2><span>{identified.length} {identified.length === 1 ? "título" : "títulos"}</span></div>
          <div className="search"><Search /><input aria-label="Buscar jogo" placeholder="Buscar no acervo" value={query} onChange={e => setQuery(e.target.value)} /></div>
        </div>
        <div className="toolbar">
          <div className="chips" role="group" aria-label="Filtrar acervo">
            <button className="chip" aria-pressed={platform === null} onClick={() => setPlatform(null)}>Todos</button>
            {platforms.map(p => <button className="chip" key={p} aria-pressed={platform === p} onClick={() => setPlatform(p)}>{platformName(p)}</button>)}
            {unknown > 0 && <button className="chip" aria-pressed={platform === "?"} onClick={() => setPlatform("?")}>Não identificados <span>{unknown}</span></button>}
          </div>
          <div className="seg" role="group" aria-label="Visualização">
            <button aria-label="Grade" title="Grade" aria-pressed={view === "grid"} onClick={() => changeView("grid")}><LayoutGrid /></button>
            <button aria-label="Lista" title="Lista" aria-pressed={view === "list"} onClick={() => changeView("list")}><List /></button>
          </div>
        </div>
        {!shown.length && <p className="empty">Nenhum jogo encontrado com esses filtros.</p>}
        <div ref={shelf} className={view === "grid" ? "sleeve-grid" : "catalog-list"}>
          {shown.map(discs => {
            const game = discs.find(d => d.playing) ?? discs[0];
            const multi = discs.length > 1;
            const title = splitTitle(multi ? editionTitle(game.title) : game.title);
            const seconds = discs.reduce((sum, d) => sum + d.seconds_played, 0);
            const href = `#/game/${game.id}`;
            // the discs of an edition share one RetroAchievements set: any synced disc speaks for all
            const achievements = discs.map(d => d.achievements).filter(a => a !== null)
              .sort((a, b) => (b!.synced_at ?? "").localeCompare(a!.synced_at ?? ""))[0] ?? null;
            return (
              <article className="sleeve" data-selected={discs === selected} key={discs[0].id}>
                <button className="sleeve-link" data-browse data-edition={discs[0].id} aria-pressed={discs === selected}
                  aria-label={`Destacar ${title.name}`} onClick={() => setSelection(discs[0].id)}>
                  {discs === selected && <span className="shelf-ticket" aria-hidden="true"><Eye /><span>Em destaque</span></span>}
                  <span className="sleeve-art"><Cover key={game.id} game={game} /></span>
                  <span className="sleeve-copy">
                    <span className="eyebrow">{platformName(game.platform)}</span>
                    <strong className="sleeve-title">{title.name}</strong>
                    <span className="sleeve-meta">{game.playing ? "Jogando agora" : seconds ? formatDuration(seconds) + " de jogo" : "Nunca jogado"}</span>
                    {view === "list" ? (achievements || multi) && (
                      <span className="sleeve-meta list-extra">
                        {achievements && `${achievements.earned}/${achievements.total} conquistas`}
                        {multi && <span className="disc-count"><Disc3 />{discs.length} discos</span>}
                      </span>
                    ) : multi && <span className="disc-count"><Disc3 />{discs.length} discos</span>}
                  </span>
                </button>
                {game.identified && game.has_emulator && !game.playing && !multi
                  ? <button className="sleeve-action" aria-label={`Jogar ${title.name}`} title="Jogar" onClick={() => play(game)}><Play /></button>
                  : <a className="sleeve-action" href={href} aria-label={multi ? `Escolher disco de ${title.name}` : `Detalhes de ${title.name}`} title={multi ? "Escolher disco" : "Ver ficha"}><ArrowUpRight /></a>}
              </article>
            );
          })}
        </div>
      </section>
    </>
  );
}
