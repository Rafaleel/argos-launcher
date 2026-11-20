import { useEffect, useState } from "react";
import { ArrowLeft, Check, Play, Trophy } from "lucide-react";
import type { Ctx } from "../App";
import { AchievementSummary, api, formatDuration, GameTime } from "../api";
import { Cover, Eye, localDate, platformName, splitTitle } from "../ui";
import { collectEditions, discNumber, editionTitle } from "../collection";
import { GameAchievements } from "./GameAchievements";
import { GameVideo, GameTextures } from "./GameDolphin";

type Tab = "achievements" | "video" | "textures";

export function GamePage({ id, games, loaded, info, notify, refresh, play }: Ctx & { id: number }) {
  const game = games.find(g => g.id === id);
  // discs of one edition share a RetroAchievements set: show whichever disc was synced
  const editionSummary = (collectEditions(games).find(group => group.some(d => d.id === id)) ?? [])
    .map(d => d.achievements).find(a => a) ?? null;
  const [history, setHistory] = useState<GameTime[] | null>(null);
  const [summary, setSummary] = useState<AchievementSummary | null>(editionSummary);
  // where the player stopped: the newest rich presence line of any disc of the edition
  const place = (collectEditions(games).find(group => group.some(d => d.id === id)) ?? [])
    .map(d => d.presence).filter(p => p !== null)
    .sort((a, b) => (b!.at ?? "").localeCompare(a!.at ?? ""))[0] ?? null;
  const [tab, setTab] = useState<Tab | null>(null);
  useEffect(() => {
    let active = true;
    api.statsGames().then(rows => { if (active) setHistory(rows); }).catch(() => undefined);
    return () => { active = false; };
  }, [id, game?.seconds_played]);
  useEffect(() => { setSummary(editionSummary); }, [editionSummary]);

  if (!game) {
    return loaded ? <p className="muted">Jogo não encontrado. <a href="#/">Voltar ao acervo</a></p> : null;
  }
  const discs = collectEditions(games).find(group => group.some(d => d.id === id)) ?? [game];
  const multi = discs.length > 1;
  const { name, tags } = splitTitle(multi ? editionTitle(game.title) : game.title);
  const time = history?.find(row => row.game_id === id);
  const canPlay = game.identified && game.has_emulator && !game.playing;
  const achievementLabel = summary ? "Conquistas" : game.ra_id ? "Sincronizar conquistas" : "Vincular conquistas";
  const tabs: [Tab, string][] = [["achievements", achievementLabel]];
  if (game.dolphin && info) tabs.push(["video", "Vídeo"], ["textures", "Texturas HD"]);

  return (
    <>
      <a className="back" href="#/"><ArrowLeft size={16} /> Voltar ao acervo</a>
      <div className="dossier">
        <div className="insert-sleeve"><div className="dossier-art"><Cover game={game} /></div></div>
        <div className="dossier-info">
          <div className="kicker"><span className="signal" />{platformName(game.platform)}{tags && ` · ${tags}`}</div>
          <h1>{name}</h1>
          {multi && <nav className="disc-picker" aria-label="Disco em exibição">
            {discs.map(d => {
              const used = d.playing || d.seconds_played > 0 || history?.some(row => row.game_id === d.id);
              return (
                <a key={d.id} href={`#/game/${d.id}`} aria-current={d.id === id ? "page" : undefined}>
                  <span className="disc-mini" aria-hidden="true" />
                  <span><b>Disco {discNumber(d.title)}</b>
                    <small>{d.playing ? "Jogando agora" : used ? `${formatDuration(d.seconds_played)} de jogo` : history ? "Ainda não jogado" : "—"}</small></span>
                  {d.id === id && <Check aria-hidden="true" />}
                </a>
              );
            })}
          </nav>}
          <div className="facts">
            {!multi && <div className="fact"><span className="eyebrow">Tempo jogado</span><b>{formatDuration(game.seconds_played)}</b></div>}
            <div className="fact"><span className="eyebrow">{multi ? "Sessões do disco" : "Sessões"}</span><b>{history ? time?.sessions ?? 0 : "—"}</b></div>
            <div className="fact"><span className="eyebrow">Última vez</span><b>{history ? localDate(time?.last_played ?? null) : "—"}</b></div>
            {place && <div className="fact" title={place.at ? `Informado pelo RetroAchievements em ${new Date(place.at).toLocaleString("pt-BR")}` : undefined}>
              <span className="eyebrow">Onde você parou</span><b>{place.message}</b></div>}
          </div>
          <div className="row insert-actions">
            <button className="btn primary big" disabled={!canPlay} onClick={() => play(game)}>
              <Play fill="currentColor" /> {game.playing ? "Jogando agora" : multi ? `Jogar disco ${discNumber(game.title)}` : "Jogar"}
            </button>
            {!game.has_emulator && game.identified && <a className="btn ghost" href="#/emulators">Configurar emulador de {platformName(game.platform)}</a>}
          </div>
        </div>
        {summary && <Eye value={summary.earned} total={summary.total} label="conquistas" gold />}
      </div>
      <div className="tabs" role="group" aria-label="Opções do jogo">
        {tabs.map(([k, label]) => (
          <button key={k} aria-expanded={tab === k} aria-controls="game-options" onClick={() => setTab(tab === k ? null : k)}>
            {k === "achievements" && <Trophy size={14} />} {label}
          </button>
        ))}
      </div>
      <div id="game-options">
        {tab === "achievements" && <GameAchievements gameId={id} notify={notify} onChange={s => { setSummary(s); refresh().catch(() => undefined); }} />}
        {tab === "video" && info && <GameVideo gameId={id} notify={notify} />}
        {tab === "textures" && info && <GameTextures gameId={id} info={info} notify={notify} />}
      </div>
    </>
  );
}
