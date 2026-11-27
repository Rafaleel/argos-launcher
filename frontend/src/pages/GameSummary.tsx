import { useEffect, useState } from "react";
import { ArrowRight, BookOpen, Circle, Clock, Crosshair, Flag, Gauge, Heart, LucideIcon, Map as MapIcon, PlusSquare, Radio, RefreshCw, Save, Skull, Trophy } from "lucide-react";
import { AchievementSummary, api, formatDuration, Game, GameProgress, GameTime, Milestones } from "../api";
import { parsePresence } from "../presence";
import { localDate, localTime } from "../ui";

const dayFmt = new Intl.DateTimeFormat("pt-BR", { day: "numeric", month: "short", year: "numeric" });
export type Place = { message: string; at: string | null };

const SOURCE_LABELS: Record<string, string> = {
  ram: "RAM",
  achievements: "Conquistas",
  playtime: "Tempo",
};

function formatHours(h: number): string {
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  return `${h.toFixed(h >= 10 ? 0 : 1).replace(".", ",")} h`;
}

// The emoji a rich presence script puts before a fact, as an SVG. Anything unknown gets a plain dot: no emoji is ever drawn.
const ICONS: Record<string, LucideIcon> = {
  "🗺": MapIcon, "🔫": Crosshair, "❤": Heart, "🧟": Skull, "🏥": PlusSquare, "📝": Save, "⏰": Clock, "⏱": Clock,
};
const iconFor = (emoji: string | null): LucideIcon => (emoji && ICONS[emoji.replace("\uFE0F", "")]) || Circle;

function Meter({ value, total, gold }: { value: number; total: number; gold?: boolean }) {
  return (
    <div className="meter gm-meter" role="img" aria-label={`${value} de ${total}`}>
      <i className={gold ? "gold" : undefined} style={{ width: `${total ? Math.min(100, (value / total) * 100) : 0}%` }} />
    </div>
  );
}

export function GameSummary({ game, discs, place, summary, story, progress, onProgressChange, notify, time, history, openTab }: {
  game: Game; discs: Game[]; place: Place | null; summary: AchievementSummary | null; story: Milestones | null;
  progress: GameProgress | null; onProgressChange: (p: GameProgress) => void; notify: (msg: string) => void;
  time: GameTime | undefined; history: boolean; openTab: (tab: "achievements" | "story") => void;
}) {
  const [recentDays, setRecentDays] = useState<{ day: string; seconds: number; sessions: number }[]>([]);
  const [ttbDraft, setTtbDraft] = useState<string>("");
  const [savingTtb, setSavingTtb] = useState(false);
  const [recomputing, setRecomputing] = useState(false);
  const discKey = discs.map((d) => d.id).join(",");

  useEffect(() => {
    setTtbDraft(progress?.ttb_hours != null ? String(progress.ttb_hours) : "");
  }, [game.id, progress?.ttb_hours]);

  async function saveTtb(nextVal: number | null) {
    setSavingTtb(true);
    try {
      const updated = await api.saveProgressConfig(game.id, nextVal);
      onProgressChange(updated);
      notify(nextVal === null ? "Tempo médio removido." : "Tempo médio salvo.");
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingTtb(false);
    }
  }

  async function handleTtbSubmit(e: React.FormEvent) {
    e.preventDefault();
    const raw = ttbDraft.trim().replace(",", ".");
    if (!raw) {
      await saveTtb(null);
      return;
    }
    const parsedNum = Number(raw);
    if (!Number.isFinite(parsedNum) || parsedNum < 0.5 || parsedNum > 1000) {
      notify("Informe um tempo entre 0,5 e 1000 horas.");
      return;
    }
    await saveTtb(parsedNum);
  }

  async function handleRecompute() {
    setRecomputing(true);
    try {
      const updated = await api.recomputeProgress(game.id);
      onProgressChange(updated);
      notify("Estimativa recalculada.");
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    } finally {
      setRecomputing(false);
    }
  }

  useEffect(() => {
    let active = true;
    const ids = new Set(discs.map((d) => d.id));
    api.journal(null).then((page) => {
      if (!active) return;
      const matches = page.days
        .map(({ day, games: rows }) => {
          const mine = rows.filter((r) => ids.has(r.game_id));
          if (!mine.length) return null;
          return {
            day,
            seconds: mine.reduce((s, r) => s + r.seconds, 0),
            sessions: mine.reduce((s, r) => s + r.sessions, 0),
          };
        })
        .filter((x): x is { day: string; seconds: number; sessions: number } => x !== null)
        .slice(0, 3);
      setRecentDays(matches);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [discKey, game.seconds_played]);

  const parsed = place ? parsePresence(place.message) : null;
  const next = story?.supported ? story.items.find((m) => !m.reached) : undefined;
  const achPct = summary && summary.total > 0 ? Math.round((summary.earned / summary.total) * 100) : null;
  const storyPct = story?.supported && story.total > 0 ? Math.round((story.reached / story.total) * 100) : null;

  return (
    <div className="gm-stack">
      <section className="panel gm-progress" aria-label="Progresso estimado">
        <div className="gm-place-top">
          <div className="kicker">
            <span className="signal" />
            Progresso estimado
            {progress?.available && progress.scenario && ` · ${progress.scenario}`}
          </div>
          <div className="gm-place-badges">
            {progress?.available && progress.sources.map((src) => (
              <span key={src} className="ofc-pill muted">{SOURCE_LABELS[src] ?? src}</span>
            ))}
            {progress?.available && (
              <button type="button" className="btn ghost gm-recompute-btn" disabled={recomputing} onClick={handleRecompute}>
                <RefreshCw size={13} aria-hidden="true" /> {recomputing ? "Recalculando…" : "Recalcular"}
              </button>
            )}
          </div>
        </div>

        {progress?.available ? (
          <div className="gm-progress-body">
            <div className="gm-progress-head">
              <strong className="gm-progress-num num">
                {progress.margin >= 10 ? "~" : ""}{Math.round(progress.mean)}%
                <small> ± {Math.round(progress.margin)}%</small>
              </strong>
              <span className="muted num">
                Intervalo 90%: {Math.round(progress.lower)}% a {Math.round(progress.upper)}%
                {progress.remaining_hours && progress.mean < 99.5 && (
                  <> · Restante: ~{formatHours(progress.remaining_hours.mean)}</>
                )}
                {progress.pace_pct_per_hour != null && progress.pace_pct_per_hour > 0 && (
                  <> · Ritmo: {progress.pace_pct_per_hour.toFixed(1).replace(".", ",")}%/h</>
                )}
              </span>
            </div>

            <div
              className="meter gm-meter gm-ci-meter"
              role="img"
              aria-label={`Estimativa ${Math.round(progress.mean)}% entre ${Math.round(progress.lower)}% e ${Math.round(progress.upper)}%`}
            >
              <span
                className="gm-ci-band"
                style={{
                  left: `${progress.lower}%`,
                  width: `${Math.max(2, progress.upper - progress.lower)}%`,
                }}
              />
              <i className={progress.mean >= 99.5 ? "gold" : undefined} style={{ width: `${progress.mean}%` }} />
            </div>

            {progress.scenarios.length > 1 && (
              <ul className="gm-scenarios" aria-label="Progresso por cenário">
                {progress.scenarios.map((sc) => (
                  <li key={sc.scenario || "default"} className={sc.scenario === progress.scenario ? "active" : undefined}>
                    <span>{sc.scenario || "História"}</span>
                    <b className="num">{Math.round(sc.mean)}% ± {Math.round(sc.margin)}%</b>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <p className="muted">
            Sem estimativa ainda. Jogue com marcos do RetroAchievements ou informe abaixo o tempo médio para zerar (h) para estimar pelo tempo jogado.
          </p>
        )}

        <form className="gm-ttb-form" onSubmit={handleTtbSubmit}>
          <label className="gm-ttb-label" htmlFor={`ttb-${game.id}`}>
            <Gauge size={14} aria-hidden="true" /> Tempo médio para zerar (h)
          </label>
          <input
            id={`ttb-${game.id}`}
            type="number"
            step="any"
            min="0.5"
            max="1000"
            placeholder="ex.: 10"
            value={ttbDraft}
            onChange={(e) => setTtbDraft(e.target.value)}
            className="gm-ttb-input num"
          />
          <button type="submit" className="btn ghost" disabled={savingTtb}>
            {savingTtb ? "Salvando…" : "Salvar"}
          </button>
          {progress?.ttb_hours != null && (
            <button type="button" className="btn ghost" disabled={savingTtb} onClick={() => saveTtb(null)}>
              Limpar
            </button>
          )}
        </form>
      </section>

      <section className="panel gm-place" aria-label="Onde você parou">
        <div className="gm-place-top">
          <div className="kicker"><span className="signal" />Onde você parou</div>
          <div className="gm-place-badges">
            {game.playing && (
              <span className="ofc-pill ok"><Radio size={13} aria-hidden="true" /> Ao vivo</span>
            )}
            {place?.at && (
              <span className="ofc-pill muted num">Atualizado em {localTime(place.at)}</span>
            )}
          </div>
        </div>

        {parsed && place ? (
          <>
            {parsed.headline && <p className="gm-place-head">{parsed.headline}</p>}
            {parsed.chips.length > 0 && (
              <ul className="gm-chips">
                {parsed.chips.map((c, i) => {
                  const Icon = iconFor(c.icon);
                  return (
                    <li key={i} className="gm-chip">
                      <span className="gm-chip-icon" aria-hidden="true"><Icon size={17} /></span>
                      <span className="gm-chip-copy">
                        {c.label && <small>{c.label}</small>}
                        <b className="num">{c.value}</b>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        ) : (
          <div className="gm-place-empty">
            <p className="muted">
              Ainda sem registro de onde você parou. Jogue pelo Argos com o jogo vinculado ao RetroAchievements e o Dolphin logado para registrar automaticamente.
            </p>
            {!game.ra_id && (
              <button type="button" className="btn ghost" onClick={() => openTab("achievements")}>
                Vincular RetroAchievements <ArrowRight size={15} />
              </button>
            )}
          </div>
        )}
      </section>

      <div className="gm-stat-grid">
        <section className="panel gm-stat">
          <div className="gm-stat-head">
            <span className="eyebrow"><Trophy size={13} aria-hidden="true" /> Conquistas</span>
            {achPct !== null && <span className="ofc-pill ok num">{achPct}%</span>}
          </div>
          {summary ? (
            <div className="gm-stat-body">
              <b className="gm-stat-num num">{summary.earned} <small>de {summary.total}</small></b>
              <Meter value={summary.earned} total={summary.total} gold />
              <p className="muted num">{summary.points_earned} de {summary.points_total} pontos · sincronizado em {localDate(summary.synced_at)}</p>
            </div>
          ) : (
            <p className="muted gm-stat-empty">
              {game.ra_id ? "Vinculado, mas ainda não sincronizado." : "Sem vínculo com o RetroAchievements."}
            </p>
          )}
          <div className="gm-stat-foot">
            <button type="button" className="btn ghost" onClick={() => openTab("achievements")}>
              Ver conquistas <ArrowRight size={15} />
            </button>
          </div>
        </section>

        {story?.supported && (
          <section className="panel gm-stat">
            <div className="gm-stat-head">
              <span className="eyebrow"><Flag size={13} aria-hidden="true" /> História</span>
              {storyPct !== null && (
                <span className={`ofc-pill ${story.reached === story.total ? "ok" : "warn"} num`}>{storyPct}%</span>
              )}
            </div>
            {story.total > 0 ? (
              <div className="gm-stat-body">
                <b className="gm-stat-num num">{story.reached} <small>de {story.total}</small></b>
                <Meter value={story.reached} total={story.total} />
                <p className="muted">
                  {next ? <>Próximo: <strong className="gm-next-inline">{next.name}</strong></> : "Todos os marcos alcançados."}
                </p>
              </div>
            ) : (
              <p className="muted gm-stat-empty">A lista é baixada na primeira vez que você joga pelo Argos.</p>
            )}
            <div className="gm-stat-foot">
              <button type="button" className="btn ghost" onClick={() => openTab("story")}>
                Ver marcos <ArrowRight size={15} />
              </button>
            </div>
          </section>
        )}

        <section className="panel gm-stat">
          <div className="gm-stat-head">
            <span className="eyebrow"><Clock size={13} aria-hidden="true" /> Tempo jogado</span>
            {history && time && time.sessions > 0 && (
              <span className="ofc-pill muted num">{time.sessions} {time.sessions === 1 ? "sessão" : "sessões"}</span>
            )}
          </div>
          <div className="gm-stat-body">
            <b className="gm-stat-num gm-stat-red num">{formatDuration(game.seconds_played)}</b>
            <p className="muted">
              {history
                ? time?.last_played
                  ? `Última sessão em ${localDate(time.last_played)}`
                  : "Nenhuma sessão registrada para este disco."
                : "Carregando histórico…"}
            </p>
          </div>
          {history && time && time.sessions > 0 && recentDays.length === 0 && (
            <div className="gm-stat-foot">
              <a className="btn ghost" href="#/stats">Ver histórico no diário <ArrowRight size={15} /></a>
            </div>
          )}
        </section>
      </div>

      {recentDays.length > 0 && (
        <section className="panel gm-recent" aria-label="Sessões nos últimos dias">
          <div className="gm-recent-head">
            <span className="eyebrow"><BookOpen size={13} aria-hidden="true" /> Sessões nos últimos dias</span>
            <a className="text-link gm-recent-link" href="#/stats">Ver diário completo <ArrowRight size={14} /></a>
          </div>
          <ul className="gm-recent-list">
            {recentDays.map((d) => (
              <li key={d.day} className="gm-recent-row">
                <time dateTime={d.day}>{dayFmt.format(new Date(d.day + "T12:00:00"))}</time>
                <span className="muted num">{d.sessions} {d.sessions === 1 ? "sessão" : "sessões"}</span>
                <strong className="num">{formatDuration(d.seconds)}</strong>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
