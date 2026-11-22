import { useEffect, useMemo, useState } from "react";
import { ArrowRight, ArrowUpRight, ChevronDown, ChevronUp, Clock3, Gamepad2, Layers } from "lucide-react";
import { api, By, formatDuration, Game, GameTime, Period, PlatformTime } from "../api";
import { collectEditions, editionTitle } from "../collection";
import { Journal } from "./Journal";
import { Cover, Panel, platformName, splitTitle } from "../ui";

type RankRow = { id: string; label: string; seconds: number; href?: string };

function RankingList({ rows, total, tone }: { rows: RankRow[]; total: number; tone: "gold" | "red" }) {
  const max = Math.max(1, ...rows.map((r) => r.seconds));
  return (
    <ol className="act-bars">
      {rows.map((r, i) => {
        const share = total > 0 ? Math.round((r.seconds / total) * 100) : 0;
        const pct = (r.seconds / max) * 100;
        return (
          <li className="act-bar-item" key={r.id}>
            <div className="act-bar-head">
              <span className="act-bar-name">
                <span className="act-rank num">{String(i + 1).padStart(2, "0")}</span>
                {r.href ? <a href={r.href}>{r.label}</a> : <span>{r.label}</span>}
              </span>
              <span className="act-bar-val num">
                <b>{formatDuration(r.seconds)}</b>
                <small>{share}%</small>
              </span>
            </div>
            <div className="act-bar-track" aria-hidden="true">
              <div className={`act-bar-fill ${tone}`} style={{ width: `${Math.max(pct, r.seconds > 0 ? 2 : 0)}%` }} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

const periodLabel = (p: string, by: By) => {
  if (by === "month") return new Date(`${p}-01T12:00:00`).toLocaleDateString("pt-BR", { month: "short" });
  const d = new Date(`${p}T12:00:00`);
  return by === "week" ? d.toLocaleDateString("pt-BR", { day: "numeric", month: "numeric" }) : d.toLocaleDateString("pt-BR", { day: "numeric" });
};

const periodFull = (p: string, by: By) => {
  if (by === "month") return new Date(`${p}-01T12:00:00`).toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
  const d = new Date(`${p}T12:00:00`);
  const formatted = d.toLocaleDateString("pt-BR", { day: "numeric", month: "short", year: "numeric" });
  return by === "week" ? `Semana de ${formatted}` : formatted;
};

export function Stats({ games }: { games: Game[] }) {
  const [platforms, setPlatforms] = useState<PlatformTime[]>([]);
  const [top, setTop] = useState<GameTime[] | null>(null);
  const [periodsState, setPeriodsState] = useState<{ by: By; rows: Period[] }>({ by: "day", rows: [] });
  const [by, setBy] = useState<By>("day");
  const [activePeriod, setActivePeriod] = useState<string | null>(null);
  const [showAllGames, setShowAllGames] = useState(false);

  useEffect(() => {
    let alive = true;
    api.statsPlatforms().then((r) => { if (alive) setPlatforms(r); }).catch(() => undefined);
    api.statsGames().then((r) => { if (alive) setTop(r); }).catch(() => { if (alive) setTop([]); });
    return () => { alive = false; };
  }, [games]);

  useEffect(() => {
    let alive = true;
    setActivePeriod(null);
    api.statsPeriods(by).then((rows) => { if (alive) setPeriodsState({ by, rows }); }).catch(() => undefined);
    return () => { alive = false; };
  }, [by, games]);

  const gameMap = useMemo(() => new Map(games.map((g) => [g.id, g])), [games]);

  const titles = useMemo(() => {
    if (!top) return [];
    return collectEditions(top.map((row) => ({
      ...row, id: row.game_id, identified: row.platform !== null,
    }))).map((group) => {
      const first = group[0];
      const available = group.find((row) => gameMap.has(row.id));
      const coverGame = available ? gameMap.get(available.id)! : { id: first.id, identified: first.identified, title: first.title, platform: first.platform };
      return {
        id: first.id,
        name: splitTitle(editionTitle(first.title)).name,
        platform: first.platform,
        seconds: group.reduce((sum, row) => sum + row.seconds, 0),
        sessions: group.reduce((sum, row) => sum + row.sessions, 0),
        href: available ? `#/game/${available.id}` : undefined,
        coverGame,
      };
    }).sort((a, b) => b.seconds - a.seconds);
  }, [top, gameMap]);

  if (top === null) return <p className="muted" role="status">Carregando estatísticas…</p>;

  if (top.length === 0) {
    return (
      <section className="act-empty" aria-label="Sem atividade registrada">
        <div>
          <div className="kicker"><span className="signal" />Diário e estatísticas</div>
          <h2>Nenhuma sessão registrada ainda</h2>
          <p className="muted">
            Abra qualquer jogo pelo Argos para começar a registrar seu tempo, construir seu diário de sessões e acompanhar seu ritmo por plataforma.
          </p>
          <div className="spot-actions">
            <a className="btn primary big" href="#/">Explorar o Acervo <ArrowRight size={16} /></a>
          </div>
        </div>
        <div className="empty-art" aria-hidden="true"><span /></div>
      </section>
    );
  }

  const periods = periodsState.rows;
  const shownBy = periodsState.by;
  const total = top.reduce((a, g) => a + g.seconds, 0);
  const sessions = top.reduce((a, g) => a + g.sessions, 0);
  const avgSession = sessions > 0 ? Math.round(total / sessions) : 0;
  const maxPeriod = Math.max(0, ...periods.map((p) => p.seconds));
  const windowTotal = periods.reduce((sum, p) => sum + p.seconds, 0);
  const focused = periods.find((p) => p.period === activePeriod) ?? null;
  const leader = titles[0];
  const visibleTitles = showAllGames ? titles : titles.slice(0, 5);
  const platformTotal = platforms.reduce((sum, p) => sum + p.seconds, 0);

  return (
    <div className="act-stack">
      <section className="panel act-hero" aria-label="Resumo da atividade">
        <div className="act-hero-stats">
          <div className="act-total-block">
            <span className="eyebrow"><Clock3 size={13} aria-hidden="true" /> Tempo total registrado</span>
            <strong className="act-total-num num">{formatDuration(total)}</strong>
          </div>
          <div className="act-mini-kpis">
            <div>
              <span className="eyebrow">Jogos jogados</span>
              <b className="num">{titles.length}</b>
            </div>
            <div>
              <span className="eyebrow">Sessões</span>
              <b className="num">{sessions}</b>
            </div>
            <div>
              <span className="eyebrow">Média / sessão</span>
              <b className="num">{formatDuration(avgSession)}</b>
            </div>
          </div>
          {leader && (
            <div className="act-top-game">
              <span className="act-top-cover"><Cover key={leader.coverGame.id} game={leader.coverGame} /></span>
              <div className="act-top-copy">
                <span className="eyebrow">Mais jogado</span>
                {leader.href ? (
                  <a className="act-top-title" href={leader.href}>{leader.name} <ArrowUpRight size={15} aria-hidden="true" /></a>
                ) : (
                  <strong className="act-top-title">{leader.name}</strong>
                )}
                <span className="muted act-top-meta num">
                  {platformName(leader.platform)} · {formatDuration(leader.seconds)} · {leader.sessions} {leader.sessions === 1 ? "sessão" : "sessões"}
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="act-chart-box">
          <div className="act-chart-head">
            <div>
              <h3>Ritmo recente</h3>
              <p className="muted act-chart-readout num">
                {focused
                  ? `${periodFull(focused.period, shownBy)}: ${formatDuration(focused.seconds)}`
                  : `Total no período: ${formatDuration(windowTotal)}`}
              </p>
            </div>
            <div className="seg" role="group" aria-label="Agrupar por">
              {(["day", "week", "month"] as By[]).map((b) => (
                <button type="button" key={b} aria-pressed={by === b} onClick={() => setBy(b)}>
                  {{ day: "Dias", week: "Semanas", month: "Meses" }[b]}
                </button>
              ))}
            </div>
          </div>

          <div className="act-chart-stage">
            {maxPeriod > 0 && <span className="act-chart-scale num" aria-hidden="true">{formatDuration(maxPeriod)}</span>}
            <div className="act-columns" onMouseLeave={() => setActivePeriod(null)}>
              {periods.map((p) => {
                const isPeak = maxPeriod > 0 && p.seconds === maxPeriod;
                const isActive = activePeriod === p.period;
                const height = maxPeriod > 0 && p.seconds > 0 ? Math.max(4, (p.seconds / maxPeriod) * 100) : 0;
                return (
                  <button
                    type="button"
                    key={p.period}
                    className={`act-col ${p.seconds === 0 ? "empty" : ""} ${isPeak ? "peak" : ""} ${isActive ? "active" : ""}`}
                    aria-label={`${periodFull(p.period, shownBy)}: ${formatDuration(p.seconds)}`}
                    onClick={() => setActivePeriod(p.period)}
                    onMouseEnter={() => setActivePeriod(p.period)}
                    onFocus={() => setActivePeriod(p.period)}
                    onBlur={() => setActivePeriod((cur) => (cur === p.period ? null : cur))}
                  >
                    <span className="act-col-bar-wrap">
                      <span className="act-col-bar" style={{ height: p.seconds > 0 ? `${height}%` : "2px" }} />
                    </span>
                    <span className="act-col-label">{periodLabel(p.period, shownBy)}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      <div className="act-split">
        <Journal games={games} />

        <div className="act-rankings">
          <Panel
            title="Por jogo"
            sub={<span className="act-panel-meta"><Gamepad2 size={13} aria-hidden="true" /> {titles.length} {titles.length === 1 ? "título" : "títulos"}</span>}
            action={titles.length > 5 && (
              <button className="btn ghost act-more-btn" onClick={() => setShowAllGames((v) => !v)}>
                {showAllGames ? <><ChevronUp size={15} /> Mostrar menos</> : <><ChevronDown size={15} /> Ver todos ({titles.length})</>}
              </button>
            )}
          >
            <RankingList
              rows={visibleTitles.map((g) => ({ id: String(g.id), label: g.name, seconds: g.seconds, href: g.href }))}
              total={total}
              tone="gold"
            />
          </Panel>

          <Panel
            title="Por plataforma"
            sub={<span className="act-panel-meta"><Layers size={13} aria-hidden="true" /> {platforms.length} {platforms.length === 1 ? "plataforma" : "plataformas"}</span>}
          >
            <RankingList
              rows={platforms.map((p) => ({ id: p.platform ?? "-", label: platformName(p.platform), seconds: p.seconds }))}
              total={platformTotal}
              tone="red"
            />
          </Panel>
        </div>
      </div>
    </div>
  );
}
