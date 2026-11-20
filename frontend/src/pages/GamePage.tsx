import { useEffect, useState } from "react";
import { ArrowLeft, Play } from "lucide-react";
import type { Ctx } from "../App";
import { AchievementSummary, api, coverUrl, formatDuration, GameTime } from "../api";
import { Cover, Eye, localDate, platformName, splitTitle } from "../ui";
import { GameAchievements } from "./GameAchievements";
import { GameVideo, GameTextures } from "./GameDolphin";

type Tab = "achievements" | "video" | "textures";

export function GamePage({ id, games, loaded, info, notify, refresh, play }: Ctx & { id: number }) {
  const game = games.find((g) => g.id === id);
  const [time, setTime] = useState<GameTime | null>(null);
  const [summary, setSummary] = useState<AchievementSummary | null>(null);
  const [tab, setTab] = useState<Tab>("achievements");

  useEffect(() => {
    api.statsGames().then((rows) => setTime(rows.find((r) => r.game_id === id) ?? null)).catch(() => undefined);
  }, [id, game?.seconds_played]);
  useEffect(() => { setSummary(game?.achievements ?? null); }, [game?.achievements]);

  if (!game) {
    return loaded ? <p className="muted">Jogo não encontrado. <a href="#/">Voltar à biblioteca</a></p> : null;
  }
  const { name, tags } = splitTitle(game.title);
  const canPlay = game.identified && game.has_emulator && !game.playing;
  const tabs: [Tab, string][] = [["achievements", "Conquistas"]];
  if (game.dolphin && info) tabs.push(["video", "Vídeo"], ["textures", "Texturas HD"]);

  return (
    <>
      <div className="hero">
        {game.identified && <div className="hero-bg" style={{ backgroundImage: `url("${coverUrl(game.id)}")` }} />}
        <div className="hero-inner">
          <div>
            <a className="back" href="#/"><ArrowLeft size={16} /> Biblioteca</a>
            <div className="art"><Cover game={game} /></div>
          </div>
          <div>
            <div className="eyebrow">{platformName(game.platform)}{tags && ` · ${tags}`}</div>
            <h1>{name}</h1>
            <div className="facts">
              <div className="fact"><span className="eyebrow">Tempo jogado</span><b>{formatDuration(game.seconds_played)}</b></div>
              <div className="fact"><span className="eyebrow">Sessões</span><b>{time?.sessions ?? 0}</b></div>
              <div className="fact"><span className="eyebrow">Última vez</span><b>{localDate(time?.last_played ?? null)}</b></div>
            </div>
            <div className="row" style={{ marginTop: 22 }}>
              <button className="btn primary big" disabled={!canPlay} onClick={() => play(game)}>
                <Play /> {game.playing ? "Jogando agora" : "Jogar"}
              </button>
              {!game.has_emulator && game.identified && (
                <a className="btn ghost" href="#/emulators">Nenhum emulador para {platformName(game.platform)}: configurar</a>
              )}
            </div>
          </div>
          <Eye value={summary?.earned ?? 0} total={summary?.total ?? 0} label="conquistas" gold />
        </div>
      </div>

      <div className="tabs" role="tablist">
        {tabs.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      {tab === "achievements" && (
        <GameAchievements gameId={game.id} notify={notify} onChange={(s) => { setSummary(s); refresh().catch(() => undefined); }} />
      )}
      {tab === "video" && info && <GameVideo gameId={game.id} notify={notify} />}
      {tab === "textures" && info && <GameTextures gameId={game.id} info={info} notify={notify} />}
    </>
  );
}
