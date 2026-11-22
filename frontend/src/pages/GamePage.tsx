import { useEffect, useState } from "react";
import { ArrowLeft, Check, Flag, Image, LayoutDashboard, LucideIcon, Monitor, Play, Trophy } from "lucide-react";
import type { Ctx } from "../App";
import { AchievementSummary, api, formatDuration, GameTime, Milestones, Profile } from "../api";
import { Cover, Eye, localDate, platformName, splitTitle } from "../ui";
import { collectEditions, discNumber, editionTitle } from "../collection";
import { GameAchievements } from "./GameAchievements";
import { GameAchievementList } from "./GameAchievementList";
import { GameMilestones } from "./GameMilestones";
import { GameSummary } from "./GameSummary";
import { GameVideo, GameTextures } from "./GameDolphin";

type Tab = "summary" | "achievements" | "story" | "video" | "textures";
const TAB_ICON: Record<Tab, LucideIcon> = { summary: LayoutDashboard, achievements: Trophy, story: Flag, video: Monitor, textures: Image };

export function GamePage({ id, games, loaded, info, notify, refresh, play }: Ctx & { id: number }) {
  const game = games.find(g => g.id === id);
  // discs of one edition share a RetroAchievements set: show whichever disc was synced
  const editionSummary = (collectEditions(games).find(group => group.some(d => d.id === id)) ?? [])
    .map(d => d.achievements).filter(a => a !== null)
    .sort((a, b) => (b!.synced_at ?? "").localeCompare(a!.synced_at ?? ""))[0] ?? null; // newest sync
  const [history, setHistory] = useState<GameTime[] | null>(null);
  const [summary, setSummary] = useState<AchievementSummary | null>(editionSummary);
  // where the player stopped: the newest rich presence line of any disc of the edition
  const place = (collectEditions(games).find(group => group.some(d => d.id === id)) ?? [])
    .map(d => d.presence).filter(p => p !== null)
    .sort((a, b) => (b!.at ?? "").localeCompare(a!.at ?? ""))[0] ?? null;
  const [tab, setTab] = useState<Tab>("summary"); // always one section open; the summary is the first thing you see
  useEffect(() => { setTab("summary"); }, [id]);
  const [story, setStory] = useState<Milestones | null>(null);
  const [profileMeta, setProfileMeta] = useState<Profile | null>(null);
  const [profileTick, setProfileTick] = useState(0);
  // the story is read while the game runs: ask again when a play starts or ends
  useEffect(() => {
    let active = true;
    const load = () => api.milestones(id).then(m => { if (active) setStory(m); }).catch(() => undefined);
    load();
    const timer = game?.playing ? setInterval(load, 5000) : undefined;
    return () => { active = false; if (timer) clearInterval(timer); };
  }, [id, game?.playing, game?.ra_id]);
  useEffect(() => {
    let active = true;
    api.statsGames().then(rows => { if (active) setHistory(rows); }).catch(() => undefined);
    return () => { active = false; };
  }, [id, game?.seconds_played]);
  useEffect(() => {
    if (!game?.dolphin || !info) { setProfileMeta(null); return; }
    let active = true;
    api.profile(id).then(p => { if (active) setProfileMeta(p); }).catch(() => undefined);
    return () => { active = false; };
  }, [id, game?.dolphin, info, profileTick]);
  useEffect(() => { setSummary(editionSummary); }, [editionSummary]);

  if (!game) {
    return loaded ? <p className="muted">Jogo não encontrado. <a href="#/">Voltar ao acervo</a></p> : null;
  }
  const discs = collectEditions(games).find(group => group.some(d => d.id === id)) ?? [game];
  const multi = discs.length > 1;
  const { name, tags } = splitTitle(multi ? editionTitle(game.title) : game.title);
  const time = history?.find(row => row.game_id === id);
  const canPlay = game.identified && game.has_emulator && !game.playing;
  const tabs: [Tab, string][] = [["summary", "Resumo"], ["achievements", "Conquistas"]];
  if (story?.supported) tabs.push(["story", "Marcos da história"]);
  if (game.dolphin && info) tabs.push(["video", "Vídeo"], ["textures", "Texturas HD"]);
  const active: Tab = tabs.some(([k]) => k === tab) ? tab : "summary"; // a section this game does not have falls back to the summary
  const hasVideoOverride = !!profileMeta && Object.values(profileMeta.settings).some((v) => v !== undefined);
  const hasTextures = !!profileMeta?.textures?.installed;

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
      <div className="tabs" role="tablist" aria-label="Seções do jogo">
        {tabs.map(([k, label]) => {
          const Icon = TAB_ICON[k];
          const badge = k === "achievements" && summary ? `${summary.earned}/${summary.total}`
            : k === "story" && story?.supported && story.total > 0 ? `${story.reached}/${story.total}` : null;
          const dot = (k === "video" && hasVideoOverride) || (k === "textures" && hasTextures);
          return (
            <button key={k} type="button" role="tab" id={`tab-${k}`} aria-selected={active === k} aria-controls="game-panel" onClick={() => setTab(k)}>
              <Icon size={15} aria-hidden="true" /> {label}
              {badge && <span className="tab-count num">{badge}</span>}
              {dot && <span className="tab-dot" role="img" aria-label="Configurado" />}
            </button>
          );
        })}
      </div>
      <div id="game-panel" role="tabpanel" aria-labelledby={`tab-${active}`}>
        {active === "summary" && <GameSummary game={game} discs={discs} place={place} summary={summary} story={story} time={time} history={!!history} openTab={setTab} />}
        {active === "achievements" && <>
          <GameAchievements gameId={id} notify={notify} onChange={s => { setSummary(s); refresh().catch(() => undefined); }} />
          <div className="section-gap"><GameAchievementList gameId={id} version={summary?.synced_at ?? null} notify={notify} /></div>
        </>}
        {active === "story" && story?.supported && <GameMilestones story={story} />}
        {active === "video" && info && <GameVideo gameId={id} notify={notify} onProfileChange={() => setProfileTick((n) => n + 1)} />}
        {active === "textures" && info && <GameTextures gameId={id} info={info} notify={notify} onProfileChange={() => setProfileTick((n) => n + 1)} />}
      </div>
    </>
  );
}
